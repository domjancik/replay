//! Owned-buffer ABI shared by native hosts and standalone wasm32.
use std::{cell::RefCell, collections::HashMap};

const MAX_INPUT: usize = 32 * 1024 * 1024;
#[derive(Default)]
struct State {
    allocations: HashMap<usize, Box<[u8]>>,
    cache: crate::render::CachedRenderer,
    prepared: Option<(crate::model::Request, crate::model::Viewport)>,
    output: Vec<u8>,
    error: Vec<u8>,
    width: usize,
    height: usize,
}
thread_local! { static STATE:RefCell<State>=RefCell::new(State::default()); }

#[no_mangle]
pub extern "C" fn rm_renderer_abi_version() -> u32 {
    1
}

#[no_mangle]
pub extern "C" fn rm_renderer_alloc(len: usize) -> usize {
    if len == 0 || len > MAX_INPUT {
        return 0;
    }
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        let allocated: usize = state.allocations.values().map(|b| b.len()).sum();
        if allocated + len > MAX_INPUT {
            return 0;
        }
        let mut bytes = Vec::new();
        if bytes.try_reserve_exact(len).is_err() {
            return 0;
        }
        bytes.resize(len, 0);
        let mut bytes = bytes.into_boxed_slice();
        let ptr = bytes.as_mut_ptr() as usize;
        state.allocations.insert(ptr, bytes);
        ptr
    })
}

#[no_mangle]
pub extern "C" fn rm_renderer_free(ptr: usize, len: usize) {
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        if state.allocations.get(&ptr).is_some_and(|v| v.len() == len) {
            state.allocations.remove(&ptr);
        }
    });
}

#[no_mangle]
pub extern "C" fn rm_renderer_render_json(ptr: usize, len: usize) -> u32 {
    let request = STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        state.output = Vec::new();
        state.error = Vec::new();
        state.width = 0;
        state.height = 0;
        let bytes = state
            .allocations
            .get(&ptr)
            .filter(|v| len > 0 && len <= v.len())
            .ok_or_else(|| "input must be a live allocated buffer".to_string())?;
        serde_json::from_slice::<crate::model::Request>(&bytes[..len])
            .map_err(|e| format!("invalid render request: {e}"))
    });
    let result = request.and_then(|r| {
        STATE.with(|cell| {
            let mut s = cell.borrow_mut();
            s.prepared = None;
            s.cache.render(&r)
        })
    });
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        match result {
            Ok(image) => {
                state.width = image.width;
                state.height = image.height;
                state.output = image.data;
                0
            }
            Err(message) => {
                state.cache.clear();
                state.error = message.into_bytes();
                1
            }
        }
    })
}

// Additive ABI v1 operations: immutable page upload followed by visibility-only frames.
#[no_mangle]
pub extern "C" fn rm_renderer_load_json(ptr: usize, len: usize) -> u32 {
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        state.prepared = None;
        state.cache.clear();
        state.output.clear();
        state.error.clear();
        state.width = 0;
        state.height = 0;
        let result = (|| {
            let bytes = state
                .allocations
                .get(&ptr)
                .filter(|v| len > 0 && len <= v.len())
                .ok_or("input must be a live allocated buffer")?;
            let request: crate::model::Request =
                serde_json::from_slice(&bytes[..len]).map_err(|e| e.to_string())?;
            let viewport = crate::validation::validate(&request)?;
            Ok::<_, String>((request, viewport))
        })();
        match result {
            Ok(prepared) => {
                state.prepared = Some(prepared);
                0
            }
            Err(e) => {
                state.error = e.into_bytes();
                1
            }
        }
    })
}
#[no_mangle]
pub extern "C" fn rm_renderer_frame_json(ptr: usize, len: usize) -> u32 {
    STATE.with(|cell| {
        let mut state = cell.borrow_mut();
        state.output.clear();
        state.error.clear();
        state.width = 0;
        state.height = 0;
        let result = (|| {
            let bytes = state
                .allocations
                .get(&ptr)
                .filter(|v| len > 0 && len <= v.len())
                .ok_or("input must be a live allocated buffer")?;
            let visibility: Option<crate::model::Visibility> =
                serde_json::from_slice(&bytes[..len]).map_err(|e| e.to_string())?;
            if visibility.as_ref().is_some_and(|v| {
                !v.active_progress.is_finite() || !(0.0..=1.0).contains(&v.active_progress)
            }) {
                return Err("invalid active progress".into());
            }
            let (mut request, viewport) = state
                .prepared
                .take()
                .ok_or("load a page before rendering frames")?;
            request.visibility = visibility;
            let result = state.cache.render_prevalidated(&request, viewport);
            state.prepared = Some((request, viewport));
            result
        })();
        match result {
            Ok(image) => {
                state.width = image.width;
                state.height = image.height;
                state.output = image.data;
                0
            }
            Err(e) => {
                state.cache.clear();
                state.error = e.into_bytes();
                1
            }
        }
    })
}

#[no_mangle]
pub extern "C" fn rm_renderer_output_ptr() -> usize {
    STATE.with(|s| s.borrow().output.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_renderer_output_len() -> usize {
    STATE.with(|s| s.borrow().output.len())
}
#[no_mangle]
pub extern "C" fn rm_renderer_error_ptr() -> usize {
    STATE.with(|s| s.borrow().error.as_ptr() as usize)
}
#[no_mangle]
pub extern "C" fn rm_renderer_error_len() -> usize {
    STATE.with(|s| s.borrow().error.len())
}
#[no_mangle]
pub extern "C" fn rm_renderer_width() -> usize {
    STATE.with(|s| s.borrow().width)
}
#[no_mangle]
pub extern "C" fn rm_renderer_height() -> usize {
    STATE.with(|s| s.borrow().height)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn prepared_frames_match_legacy_and_invalid_load_clears_session() {
        let json=br#"{"page":{"page_id":"x","paper_size":[2,1],"groups":[],"strokes":[],"compositing_order":[]}}"#;
        fn input(bytes: &[u8]) -> usize {
            let ptr = rm_renderer_alloc(bytes.len());
            STATE.with(|s| {
                s.borrow_mut()
                    .allocations
                    .get_mut(&ptr)
                    .unwrap()
                    .copy_from_slice(bytes)
            });
            ptr
        }
        let ptr = input(json);
        assert_eq!(rm_renderer_load_json(ptr, json.len()), 0);
        let vis = input(b"null");
        assert_eq!(rm_renderer_frame_json(vis, 4), 0);
        let prepared = STATE.with(|s| s.borrow().output.clone());
        assert_eq!(rm_renderer_render_json(ptr, json.len()), 0);
        assert_eq!(prepared, STATE.with(|s| s.borrow().output.clone()));
        assert_ne!(rm_renderer_load_json(42, 10), 0);
        assert_ne!(rm_renderer_frame_json(vis, 4), 0);
        rm_renderer_free(ptr, json.len());
        rm_renderer_free(vis, 4);
    }
    #[test]
    fn rejects_invalid_and_freed_handles_without_dereferencing() {
        assert_ne!(rm_renderer_render_json(42, 100), 0);
        assert_eq!(rm_renderer_output_len(), 0);
        let ptr = rm_renderer_alloc(16);
        assert_ne!(ptr, 0);
        rm_renderer_free(ptr, 16);
        rm_renderer_free(ptr, 16);
        assert_ne!(rm_renderer_render_json(ptr, 16), 0);
        assert_eq!(rm_renderer_alloc(MAX_INPUT + 1), 0);
    }
    #[test]
    fn owned_request_returns_rgba_and_clears_previous_result_on_error() {
        let json=br#"{"page":{"page_id":"x","paper_size":[2,1],"groups":[],"strokes":[],"compositing_order":[]},"options":{"background":[17,23,31,128]}}"#;
        let ptr = rm_renderer_alloc(json.len());
        STATE.with(|s| {
            s.borrow_mut()
                .allocations
                .get_mut(&ptr)
                .unwrap()
                .copy_from_slice(json)
        });
        assert_eq!(rm_renderer_render_json(ptr, json.len()), 0);
        assert_eq!((rm_renderer_width(), rm_renderer_height()), (2, 1));
        STATE.with(|s| assert_eq!(s.borrow().output, vec![17, 23, 31, 128, 17, 23, 31, 128]));
        assert_ne!(rm_renderer_render_json(ptr, 1), 0);
        assert_eq!(rm_renderer_output_len(), 0);
        rm_renderer_free(ptr, json.len());
        STATE.with(|s| assert_eq!(s.borrow().output.capacity(), 0));
    }
}
