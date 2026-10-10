"""Perception models. All torch work is serialized through one lock (MPS is not re-entrant friendly)."""

import threading

gpu_lock = threading.RLock()
