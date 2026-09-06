"""Browser playback for server-generated Practice TTS audio."""
from __future__ import annotations

import json

from nicegui import ui


_SPEAK_JS = r"""
return await (async () => {
    const prior = window.mqInterviewSpeech;
    if (prior?.audio) {
        prior.audio.pause();
        prior.audio.currentTime = 0;
    }
    if (prior?.url) URL.revokeObjectURL(prior.url);

    let response;
    try {
        response = await fetch('/api/interview/tts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: __TEXT__, model: __MODEL__}),
        });
    } catch (error) {
        return {ok:false, error:'Could not reach the TTS service: ' + (error?.message || error)};
    }
    if (!response.ok) {
        let detail = '';
        try { detail = (await response.json()).detail || ''; } catch (_) {}
        return {ok:false, error:detail || ('TTS failed with status ' + response.status + '.')};
    }

    const url = URL.createObjectURL(await response.blob());
    const audio = new Audio(url);
    window.mqInterviewSpeech = {audio, url};
    const setStatus = message => {
        const element = document.querySelector('.interview-tts-status');
        if (element) element.textContent = message;
    };
    audio.onended = () => {
        if (window.mqInterviewSpeech?.audio === audio) setStatus('Playback finished');
        URL.revokeObjectURL(url);
    };
    audio.onerror = () => setStatus('Playback failed');
    try {
        await audio.play();
    } catch (error) {
        return {ok:false, error:'Playback was blocked. Use Replay Question to start it.'};
    }
    return {ok:true};
})()
"""


async def speak_question(text: str, model: str) -> dict:
    """Request audio from the local TTS route and play it in the browser."""
    script = _SPEAK_JS.replace("__TEXT__", json.dumps(text.strip()))
    script = script.replace("__MODEL__", json.dumps(model.strip()))
    return await ui.run_javascript(script, timeout=90.0)


async def stop_speaking() -> None:
    """Stop the current server-generated question audio in this browser tab."""
    await ui.run_javascript(r"""
        const current = window.mqInterviewSpeech;
        if (current?.audio) {
            current.audio.pause();
            current.audio.currentTime = 0;
        }
        if (current?.url) URL.revokeObjectURL(current.url);
        window.mqInterviewSpeech = null;
        const element = document.querySelector('.interview-tts-status');
        if (element) element.textContent = 'Playback stopped';
        return true;
    """, timeout=10.0)
