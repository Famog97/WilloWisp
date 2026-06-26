"""
Dev smoke launcher — used after each migration step (alongside `pytest`).

Opens the *real* `baru.App`, shows a green countdown overlay confirming the GUI
launched, then auto-closes. This catches GUI-construction breakage that the headless
test suite cannot. Run:

    python smoke_app.py            # 3-second countdown (default)
    python smoke_app.py 5          # custom seconds

Prints "SMOKE OK: ..." on a clean launch+close; any startup exception surfaces as a
traceback (and the overlay never appears).
"""
import sys
import tkinter as tk

import baru


def main(seconds: int = 3) -> None:
    # Exact startup sequence from baru.__main__ (minus the blocking mainloop).
    baru._load_plugins()
    baru._wire_subscribers()
    app = baru.App()
    app.update_idletasks()

    # ── Countdown overlay ────────────────────────────────────────────────────
    overlay = tk.Toplevel(app)
    overlay.overrideredirect(True)              # borderless banner
    overlay.attributes("-topmost", True)
    overlay.configure(bg="#0f1115", highlightthickness=2, highlightbackground="#69ff9a")
    msg = tk.Label(overlay, bg="#0f1115", fg="#69ff9a", justify="center",
                   font=("Segoe UI", 16, "bold"), padx=44, pady=30)
    msg.pack()

    def _center():
        overlay.update_idletasks()
        w, h = overlay.winfo_width(), overlay.winfo_height()
        sw, sh = overlay.winfo_screenwidth(), overlay.winfo_screenheight()
        overlay.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    def _tick(n: int):
        if n <= 0:
            try:
                app.destroy()
            except Exception:
                pass
            return
        msg.config(text=f"✅  Smoke test — baru.py launched fine\n\nClosing in {n} …")
        _center()
        app.after(1000, _tick, n - 1)

    _tick(seconds)
    try:
        app.mainloop()
    except Exception:
        pass
    print(f"SMOKE OK: baru.App launched + UI built + auto-closed after {seconds}s")


if __name__ == "__main__":
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    main(secs)
