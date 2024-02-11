const recordButton = document.getElementById('recordButton');
let mediaRecorder;
let audioContext;
let silenceTimer;
let hasSpoken = false; // Variable, um zu prüfen, ob der Nutzer gesprochen hat
let gumStream;
let analyser;
let dataArray;
let recordingStartTime;

recordButton.addEventListener('click', startRecording);

function redirectToUserPage() {
    window.location.href = '/user'
}


async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        gumStream = stream;
        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        dataArray = new Uint8Array(analyser.frequencyBinCount);

        mediaRecorder = new MediaRecorder(stream);
        const recordedChunks = [];

        mediaRecorder.addEventListener('dataavailable', function (e) {
            if (e.data.size > 0) recordedChunks.push(e.data);
        });

	mediaRecorder.addEventListener('stop', () => {
	    const blob = new Blob(recordedChunks, { 'type' : 'audio/webm' });
	    const formData = new FormData();
	    formData.append('audio', blob);

	    fetch('/upload', {
		method: 'POST',
		body: formData
	    })
	    .then(response => {
		if (response.ok && response.redirected) {
		    window.location.href = response.url;  // Weiterleitung auf die Antwort-URL
		}
	    })
	    .catch(error => {
		console.error('Error:', error);
	    });

	    hasSpoken = false;
	});

        mediaRecorder.start();
        recordingStartTime = Date.now();
        checkSilence();
    } catch (err) {
        console.error('Error accessing the microphone', err);
    }
}


function checkSilence() {
    analyser.getByteTimeDomainData(dataArray);
    let sum = 0;

    for (let i = 0; i < dataArray.length; i++) {
        let amplitude = dataArray[i] / 128 - 1;
        sum += amplitude * amplitude;
    }
    let rms = Math.sqrt(sum / dataArray.length);

    if (rms >= 0.02) { 
        hasSpoken = true;
    }

    if (hasSpoken) {
        if (rms < 0.02) { 
            if (!silenceTimer) {
                silenceTimer = setTimeout(() => {
                    mediaRecorder.stop();
                    gumStream.getTracks().forEach(track => track.stop());
                    audioContext.close();
                    recordButton.disabled = false;
                    clearTimeout(silenceTimer);
                    silenceTimer = null;
                    console.log('Recording stopped due to silence.');
                }, 400); // Stoppen nach 0,4 Sekunden Stille
            }
        } else {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }
    }

    if (mediaRecorder.state === 'recording') {
        requestAnimationFrame(checkSilence);
    }
}

recordButton.disabled = false;
