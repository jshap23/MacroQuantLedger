"""Browser-side interview recorder controlled by short NiceGUI commands."""
from __future__ import annotations

import json

from nicegui import ui


_START_RECORDING_JS = r"""
return await (async () => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        return {ok:false, error:'Audio recording is not supported in this browser.'};
    }
    const old = window.mqInterviewRecorder;
    if (old?.recording) return {ok:false, error:'A recording is already active.'};
    if (old?.dispose) old.dispose(false);

    let stream;
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: {echoCancellation:true, noiseSuppression:true, autoGainControl:true}
        });
    } catch (error) {
        const message = error?.name === 'NotAllowedError'
            ? 'Microphone permission was denied.'
            : 'Could not open the microphone: ' + (error?.message || error);
        return {ok:false, error:message};
    }

    const types = [
        'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'
    ];
    const mimeType = types.find(type => MediaRecorder.isTypeSupported(type)) || '';
    let recorder;
    try {
        recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    } catch (error) {
        stream.getTracks().forEach(track => track.stop());
        return {ok:false, error:'Could not start the recorder: ' + (error?.message || error)};
    }

    const controller = {
        stream, recorder, chunks: [], lastBlob: null, recording: true,
        startedAt: Date.now(), timer: null, recognition: null,
        recognitionRestart: null, audioContext: null, animationFrame: null,
        previewFinal: '', previewCurrent: '', recorderError: '',
    };
    window.mqInterviewRecorder = controller;

    controller.status = message => {
        const element = document.querySelector('.interview-recording-status');
        if (element) element.textContent = message;
    };
    controller.caption = message => {
        const element = document.querySelector('.interview-live-caption');
        if (element) element.textContent = message;
    };
    controller.stopTracks = () => {
        controller.stream?.getTracks().forEach(track => track.stop());
    };
    controller.stopRecognition = () => {
        clearTimeout(controller.recognitionRestart);
        if (controller.recognition) {
            controller.recognition.onend = null;
            try { controller.recognition.abort(); } catch (_) {}
            controller.recognition = null;
        }
    };
    controller.stopMeter = () => {
        if (controller.animationFrame) cancelAnimationFrame(controller.animationFrame);
        if (controller.audioContext) controller.audioContext.close().catch(() => {});
        controller.animationFrame = null;
        controller.audioContext = null;
        const meter = document.querySelector('.interview-audio-level');
        if (meter) meter.style.width = '0%';
    };
    controller.stopReplay = () => {
        if (controller.replayAudio) {
            try { controller.replayAudio.pause(); } catch (_) {}
            controller.replayAudio.onended = null;
            controller.replayAudio.onerror = null;
            controller.replayAudio = null;
        }
        if (controller.replayUrl) {
            try { URL.revokeObjectURL(controller.replayUrl); } catch (_) {}
            controller.replayUrl = null;
        }
    };
    controller.dispose = (discardAudio=true) => {
        controller.stopReplay();
        controller.recording = false;
        clearInterval(controller.timer);
        controller.stopRecognition();
        controller.stopMeter();
        controller.stopTracks();
        if (discardAudio) {
            controller.chunks = [];
            controller.lastBlob = null;
        }
    };

    recorder.ondataavailable = event => {
        if (event.data?.size) controller.chunks.push(event.data);
    };
    recorder.onerror = event => {
        controller.recorderError = event.error?.message || 'The browser recorder stopped unexpectedly.';
    };
    recorder.start(1000);

    controller.timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - controller.startedAt) / 1000);
        const minutes = String(Math.floor(seconds / 60)).padStart(2, '0');
        const remainder = String(seconds % 60).padStart(2, '0');
        controller.status('Recording ' + minutes + ':' + remainder + ' · pauses are safe');
    }, 250);

    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) {
            const context = new AudioContext();
            const source = context.createMediaStreamSource(stream);
            const analyser = context.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            const values = new Uint8Array(analyser.frequencyBinCount);
            controller.audioContext = context;
            const draw = () => {
                if (!controller.recording) return;
                analyser.getByteFrequencyData(values);
                const level = Math.min(100, values.reduce((a, b) => a + b, 0) / values.length * 1.8);
                const meter = document.querySelector('.interview-audio-level');
                if (meter) meter.style.width = level + '%';
                controller.animationFrame = requestAnimationFrame(draw);
            };
            draw();
        }
    } catch (_) {}

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const startRecognition = () => {
        if (!SpeechRecognition || !controller.recording) return;
        const recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.continuous = true;
        recognition.interimResults = true;
        controller.recognition = recognition;
        recognition.onresult = event => {
            let interim = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const text = event.results[i][0].transcript;
                if (event.results[i].isFinal) controller.previewFinal += text + ' ';
                else interim += text;
            }
            controller.previewCurrent = (controller.previewFinal + interim).trim();
            controller.caption(controller.previewCurrent);
        };
        recognition.onerror = event => {
            if (!['no-speech', 'aborted'].includes(event.error)) {
                controller.caption('Live captions unavailable (' + event.error + '); audio is still recording.');
            }
        };
        recognition.onend = () => {
            if (controller.recording) {
                controller.recognitionRestart = setTimeout(startRecognition, 250);
            }
        };
        try { recognition.start(); } catch (_) {
            if (controller.recording) {
                controller.recognitionRestart = setTimeout(startRecognition, 500);
            }
        }
    };
    startRecognition();
    controller.status('Recording 00:00 · pauses are safe');
    return {ok:true, mimeType:recorder.mimeType, liveCaptions:Boolean(SpeechRecognition)};
})()
"""


async def start_recording() -> dict:
    return await ui.run_javascript(_START_RECORDING_JS, timeout=15.0)


_STOP_RECORDING_JS = r"""
return await (async () => {
    const controller = window.mqInterviewRecorder;
    if (!controller) return {ok:false, error:'No recording is available.'};
    if (controller.recording) {
        controller.status('Finishing recording…');
        controller.recording = false;
        clearInterval(controller.timer);
        controller.stopRecognition();
        controller.stopMeter();
        try {
            controller.lastBlob = await new Promise((resolve, reject) => {
                const timeout = setTimeout(
                    () => reject(new Error('The recorder did not stop cleanly.')), 10000
                );
                controller.recorder.onstop = () => {
                    clearTimeout(timeout);
                    resolve(new Blob(controller.chunks, {
                        type: controller.recorder.mimeType || 'audio/webm'
                    }));
                };
                controller.recorder.stop();
            });
        } catch (error) {
            controller.stopTracks();
            return {ok:false, error:error?.message || String(error), retryable:false};
        }
        controller.stopTracks();
    }
    if (controller.recorderError) {
        return {
            ok:false, error:controller.recorderError,
            retryable:Boolean(controller.lastBlob), preview:controller.previewCurrent
        };
    }
    if (!controller.lastBlob?.size) {
        return {ok:false, error:'The recording was empty.', retryable:false};
    }
    controller.status('Live draft ready · audio retained for optional improvement');
    return {
        ok:true, preview:controller.previewCurrent,
        retryable:true, audioSize:controller.lastBlob.size
    };
})()
"""


async def stop_recording() -> dict:
    return await ui.run_javascript(_STOP_RECORDING_JS, timeout=20.0)


_TRANSCRIBE_JS = r"""
return await (async context => {
    const controller = window.mqInterviewRecorder;
    if (!controller) return {ok:false, error:'No recording is available.'};

    if (controller.recording) {
        controller.status('Finishing recording…');
        controller.recording = false;
        clearInterval(controller.timer);
        controller.stopRecognition();
        controller.stopMeter();
        try {
            controller.lastBlob = await new Promise((resolve, reject) => {
                const timeout = setTimeout(
                    () => reject(new Error('The recorder did not stop cleanly.')), 10000
                );
                controller.recorder.onstop = () => {
                    clearTimeout(timeout);
                    resolve(new Blob(controller.chunks, {
                        type: controller.recorder.mimeType || 'audio/webm'
                    }));
                };
                controller.recorder.stop();
            });
        } catch (error) {
            controller.stopTracks();
            return {ok:false, error:error?.message || String(error), retryable:false};
        }
        controller.stopTracks();
    }

    if (controller.recorderError) {
        return {
            ok:false, error:controller.recorderError,
            retryable:Boolean(controller.lastBlob), preview:controller.previewCurrent
        };
    }
    const blob = controller.lastBlob;
    if (!blob?.size) return {ok:false, error:'The recording was empty.', retryable:false};

    controller.status('Transcribing locally… first use may download the speech model');
    const form = new FormData();
    const type = blob.type || 'audio/webm';
    const extension = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'mp4' : 'webm';
    form.append('audio', blob, 'interview-answer.' + extension);
    form.append('language', 'en');
    form.append('context', context || '');
    try {
        const response = await fetch('/api/interview/transcribe', {method:'POST', body:form});
        let data = {};
        try { data = await response.json(); } catch (_) {}
        if (!response.ok) {
            return {
                ok:false,
                error:data.detail || ('Transcription failed with status ' + response.status + '.'),
                retryable:true, preview:controller.previewCurrent,
            };
        }
        controller.status('Transcription ready · review before submitting');
        controller.caption('');
        controller.stopReplay();
        controller.chunks = [];
        // Keep lastBlob in browser memory for the rest of this answer turn so the
        // user can replay what they said. cancel_recording()/dispose() frees it.
        return {ok:true, ...data};
    } catch (error) {
        return {
            ok:false,
            error:'Could not reach the transcription service: ' + (error?.message || error),
            retryable:true, preview:controller.previewCurrent,
        };
    }
})(__CONTEXT__)
"""


async def transcribe_recording(context: str) -> dict:
    script = _TRANSCRIBE_JS.replace("__CONTEXT__", json.dumps(context[:500]))
    return await ui.run_javascript(script, timeout=600.0)


async def cancel_recording() -> None:
    await ui.run_javascript(r"""
        const controller = window.mqInterviewRecorder;
        if (controller) {
            controller.recording = false;
            try {
                if (controller.recorder?.state !== 'inactive') {
                    controller.recorder.ondataavailable = null;
                    controller.recorder.onstop = null;
                    controller.recorder.stop();
                }
            } catch (_) {}
            controller.dispose(true);
            controller.status('Recording cancelled');
            controller.caption('');
        }
        return true;
    """, timeout=10.0)


async def replay_recording() -> dict:
    """Toggle playback of the in-memory recording for the current answer turn."""
    return await ui.run_javascript(r"""
        const controller = window.mqInterviewRecorder;
        if (!controller?.lastBlob?.size) {
            return {ok:false, error:'No recording is available to replay.'};
        }
        if (controller.replayAudio) {
            controller.stopReplay();
            return {ok:true, playing:false};
        }
        const url = URL.createObjectURL(controller.lastBlob);
        const audio = new Audio(url);
        controller.replayAudio = audio;
        controller.replayUrl = url;
        audio.onended = () => controller.stopReplay();
        audio.onerror = () => controller.stopReplay();
        try {
            await audio.play();
        } catch (error) {
            controller.stopReplay();
            return {ok:false, error:'Could not play the recording: ' + (error?.message || error)};
        }
        return {ok:true, playing:true};
    """, timeout=15.0)


async def download_recording() -> bool:
    return await ui.run_javascript(r"""
        const controller = window.mqInterviewRecorder;
        if (!controller?.lastBlob) return false;
        const url = URL.createObjectURL(controller.lastBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'interview-answer.webm';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return true;
    """, timeout=10.0)
