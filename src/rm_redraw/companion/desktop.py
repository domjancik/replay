"""Double-clickable companion UI; deliberately no background auto-start."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from rm_redraw.companion.server import create_server


def main():
    root = tk.Tk()
    root.title("rePlay USB Companion")
    root.geometry("540x380")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="rePlay USB Companion", font=("Segoe UI", 20)).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "Connect your tablet by USB and enable its USB web interface.\n"
            "Cloud and file import do not need this app."
        ),
        wraplength=490,
    ).pack(anchor="w", pady=(10, 18))
    ttk.Label(frame, text="Allow this rePlay site (exact origin)").pack(anchor="w")
    origin = tk.StringVar(value="http://127.0.0.1:8765")
    entry = ttk.Entry(frame, textvariable=origin)
    entry.pack(fill="x", pady=(4, 12))
    key = tk.StringVar()
    status = tk.StringVar(value="Stopped. Nothing is shared until you click Start.")
    messages = queue.SimpleQueue()
    server = None

    def stop():
        nonlocal server
        if server:
            server.shutdown()
            server.server_close()
            server = None
        key.set("")
        start_button.config(state="normal")
        copy_button.config(state="disabled")
        entry.config(state="normal")
        status.set("Stopped. Connection key revoked.")

    def start():
        nonlocal server
        try:
            server = create_server(origin.get(), report=messages.put)
        except (ValueError, OSError) as error:
            status.set(str(error))
            return
        threading.Thread(target=server.serve_forever, daemon=True).start()
        key.set(server.token)
        start_button.config(state="disabled")
        copy_button.config(state="normal")
        entry.config(state="disabled")
        status.set("Ready. Copy the connection key into rePlay → Import from tablet.")

    def copy_key():
        root.clipboard_clear()
        root.clipboard_append(key.get())
        status.set("Connection key copied. Paste it only into your allowed rePlay site.")

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")
    start_button = ttk.Button(buttons, text="Start USB access", command=start)
    start_button.pack(side="left")
    ttk.Button(buttons, text="Stop", command=stop).pack(side="left", padx=8)
    copy_button = ttk.Button(
        buttons, text="Copy connection key", command=copy_key, state="disabled"
    )
    copy_button.pack(side="left")
    ttk.Label(frame, textvariable=status, wraplength=490).pack(anchor="w", pady=18)
    ttk.Label(
        frame,
        text=(
            "Read-only • One allowed site • Temporary key\n"
            "Closing this window stops new requests. An active download may finish."
        ),
        wraplength=490,
    ).pack(anchor="w")

    def poll():
        while not messages.empty():
            message = messages.get_nowait()
            if server:
                status.set(message)
        root.after(200, poll)

    def close():
        stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
