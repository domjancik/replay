use std::alloc::{alloc_zeroed, dealloc, Layout};

pub use rm_pencil_kernel::rm_pencil_draw;

#[no_mangle]
pub extern "C" fn pencil_abi_version() -> u32 {
    rm_pencil_kernel::rm_pencil_abi_version()
}

#[no_mangle]
pub extern "C" fn pencil_alloc(len: usize) -> *mut u8 {
    match Layout::from_size_align(len, 8) {
        Ok(layout) if len != 0 => unsafe { alloc_zeroed(layout) },
        _ => std::ptr::null_mut(),
    }
}

/// # Safety
/// The pointer and length must be the pair returned by a successful pencil_alloc
/// call that has not yet been freed.
#[no_mangle]
pub unsafe extern "C" fn pencil_free(ptr: *mut u8, len: usize) {
    unsafe { dealloc(ptr, Layout::from_size_align(len, 8).unwrap()) }
}
