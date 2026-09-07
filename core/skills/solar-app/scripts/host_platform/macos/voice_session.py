#!/usr/bin/env python3
"""Menu-bar push-to-talk: record locally, send transcript, speak the reply."""
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import voice_config as vcfg
import voice_core as vc
from host_platform.macos import client

IDLE = "idle"
RECORDING = "recording"
PROCESSING = "processing"


@dataclass(frozen=True)
class VoiceUi:
    state: str
    menu: str
    hud: str
    title: str


class TrayVoice:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = IDLE
        self._hud = ""
        self._proc: Optional[object] = None
        self._path: Optional[Path] = None
        self._conversation_id: Optional[str] = None
        self._workspace: Optional[str] = None

    def snapshot(self) -> VoiceUi:
        with self._lock:
            if self._state == RECORDING:
                return VoiceUi(RECORDING, "Stop", self._hud or "Escuchando…", "Solar · rec")
            if self._state == PROCESSING:
                return VoiceUi(PROCESSING, "Voice", self._hud or "Pensando…", "Solar · …")
            return VoiceUi(IDLE, "Voice", self._hud, "Solar")

    def toggle(self) -> None:
        with self._lock:
            state = self._state
        if state == RECORDING:
            self.stop_async()
        elif state == IDLE:
            self.start()

    def reset_conversation(self) -> None:
        with self._lock:
            self._conversation_id = None
            self._workspace = None

    def shutdown(self) -> None:
        with self._lock:
            proc = self._proc
            path = self._path
            self._proc = None
            self._path = None
            self._state = IDLE
            self._hud = ""
        if proc is not None:
            vc._stop_rec(proc)  # type: ignore[arg-type]
        if path is not None:
            path.unlink(missing_ok=True)

    def start(self) -> None:
        vc.reap_orphan_recorders()
        ok, hint = vc.check_voice_deps(require_whisper=True)
        if not ok:
            self._fail(hint)
            return
        try:
            import voice_mic as vm  # noqa: PLC0415

            label, granted = vm.microphone_status()
            if not granted and label == "not_determined":
                vm.ensure_microphone_access()
                _, granted = vm.microphone_status()
            if not granted:
                self._fail(vm.microphone_hint_for_denied())
                return
        except ImportError:
            pass
        rec = vcfg.resolve_rec()
        if not rec:
            self._fail("Falta SoX (brew install sox).")
            return
        path = vcfg.new_capture_path(vc.voice_runtime_dir())
        vcfg.prepare_capture(path)
        argv = vcfg.rec_argv(path)
        if not argv:
            self._fail("No se pudo abrir el micrófono.")
            return
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=vcfg.subprocess_env(),
        )
        with self._lock:
            if self._state != IDLE:
                vc._stop_rec(proc)
                path.unlink(missing_ok=True)
                return
            self._state = RECORDING
            self._hud = "Escuchando…"
            self._proc = proc
            self._path = path
        threading.Thread(target=self._limit, daemon=True).start()

    def stop_async(self) -> None:
        with self._lock:
            if self._state != RECORDING:
                return
            proc = self._proc
            path = self._path
            self._proc = None
            self._state = PROCESSING
            self._hud = "Pensando…"
        threading.Thread(target=self._process, args=(proc, path), daemon=True).start()

    def _limit(self) -> None:
        for _ in range(240):
            time.sleep(0.25)
            with self._lock:
                if self._state != RECORDING:
                    return
                proc = self._proc
                if proc is not None and proc.poll() is not None:  # type: ignore[union-attr]
                    break
        with self._lock:
            if self._state == RECORDING:
                pass
            else:
                return
        self.stop_async()

    def _process(self, proc: object, path: Optional[Path]) -> None:
        try:
            if proc is not None:
                vc._stop_rec(proc)  # type: ignore[arg-type]
            if path is None or not path.is_file():
                self._fail("No se grabó audio.")
                return
            text = vc.transcribe(path).strip()
            if not client.transcript_ok(text):
                self._fail(text or "No se detectó voz.")
                return
            bootstrap = client.app_bootstrap()
            if not bootstrap:
                self._fail("Solar no está en marcha.")
                return
            if not bootstrap.get("enabled"):
                self._fail("La conversación no está activada en este servicio.")
                return
            workspace = str(bootstrap.get("workspace") or "")
            if not workspace:
                self._fail("No hay un espacio de trabajo activo.")
                return
            with self._lock:
                cid = self._conversation_id if self._workspace == workspace else None
            cid = client.app_ensure_conversation(workspace, cid)
            if not cid:
                self._fail("No se pudo abrir la conversación.")
                return
            with self._lock:
                self._conversation_id = cid
                self._workspace = workspace
                self._hud = "Pensando…"
            detail = client.app_send_turn(workspace, cid, text, uuid.uuid4().hex[:24])
            reply = client.last_assistant_text(detail)
            if not reply:
                self._fail("Solar no ha respondido.")
                return
            with self._lock:
                self._hud = reply[:180]
            vc.speak_brief(reply)
            with self._lock:
                self._state = IDLE
                self._hud = ""
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc)[:200])
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
                try:
                    vcfg.cleanup_transcript_artifacts(path)
                except Exception:  # noqa: BLE001
                    pass

    def _fail(self, message: str) -> None:
        with self._lock:
            self._state = IDLE
            self._hud = message
            proc = self._proc
            path = self._path
            self._proc = None
            self._path = None
        if proc is not None:
            vc._stop_rec(proc)  # type: ignore[arg-type]
        if path is not None:
            path.unlink(missing_ok=True)
        threading.Timer(3.5, self._clear_hud).start()

    def _clear_hud(self) -> None:
        with self._lock:
            if self._state == IDLE:
                self._hud = ""
