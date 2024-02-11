from flask import Flask, request, render_template, redirect, url_for, jsonify
import faster_whisper
from datetime import datetime, timedelta
import openai
import re
import threading
import queue
from elevenlabs import generate, set_api_key, play, stream
from flask_socketio import SocketIO
import nltk
from nltk.tokenize import word_tokenize
import sys
import os 

nltk.download('punkt')  

app = Flask(__name__)
app.config['SECRET_KEY'] = 'geheim!'
socketio = SocketIO(app)

model = faster_whisper.WhisperModel(model_size_or_path="small", device="cpu", cpu_threads=8, compute_type="float32")
set_api_key("Elevenlabs_api")
openai.api_key = "Openai_api"


audio_queue = queue.Queue()
conversation_log_lock = threading.Lock()
conversation_log = []
cancellation_flag = False
is_first_interaction = True
first_sentence_streamed = False  

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/user')
def user():
    return render_template('user.html')

@app.route('/intro')
def intro():
    return render_template('intro.html')

@app.route('/loading')
def loading():
    return render_template('loading.html')

@app.route('/narrator')
def narrator():
    return render_template('narrator.html')

@app.route('/upload', methods=['POST'])
def upload():
    global conversation_log
    if 'audio' in request.files:
        audio = request.files['audio']
        audio.save('recording.mp3')

        socketio.emit('change_frontend', {'html': 'loading.html'})

        # Transkribiere die aufgenommene Datei
        transcribed_texts, time_taken = transcribe_audio('recording.mp3')
        print("Transkribierter Text:", " ".join(transcribed_texts))
        print(f"Transkriptionszeit: {time_taken}")
        user_input = " ".join(transcribed_texts)
        with conversation_log_lock:
            conversation_log.append({"role": "user", "content": user_input})

        return process(user_input)

    return 'No audio file found', 400


@app.route('/cancel')
def cancel():
    global cancellation_flag
    cancellation_flag = True

    with audio_queue.mutex:
        print("mute")
        volume = 0
        os.system(f"amixer -D pulse sset Master {volume}%")
    
        audio_queue.queue.clear()

    socketio.emit('cancel_frontend', {'cancelled': True})

    with conversation_log_lock:
        conversation_log.clear()
    cancellation_flag = False
    return redirect(url_for('index'))



@app.route('/process/<text>')
def process(text):
    global conversation_log, is_first_interaction  

    with conversation_log_lock:
        assistant_message = ""

        for entry in conversation_log:
            if entry['role'] == 'assistant':
                assistant_message += entry['content']
            else:
                if assistant_message:
                    print(assistant_message)
                    assistant_message = ""
                print(entry)

        if assistant_message:
            print(assistant_message)

    if is_first_interaction:  
        prompt = f"Hallo ChatGPT, ich möchte an einem fesselnden und aufregenden Rollenspiel teilnehmen, bei dem du mich durch eine packende Erzählung führst. Beginne immer, am Anfang mit einem kurzen Satz aus 3-5 Wörtern. Das ist sehr wichtig!!! Das Spiel wird Entscheidungen meinerseits beinhalten. Zu Beginn werde ich dir wichtige Details wie meinen Namen, meinen Wohnort und die Ära, in der die Geschichte spielt, mitteilen. Sobald ich diese Informationen geteilt habe, möchte ich, dass du die Geschichte mit reicher und lebendiger Sprache beginnst, unter Einbeziehung einer Fülle von Adjektiven. Es wäre äußerst hilfreich, wenn du detaillierte Beschreibungen anbieten könntest, die mich tief in das Herz der Geschichte eintauchen lassen. Wann immer eine Wahlmöglichkeit auftritt, bitte ich dich, mich dazu aufzufordern zu entscheiden, welchen Weg ich einschlagen möchte. Bitte bleibe während des Spiels in deiner Rolle und konzentriere dich ausschließlich auf das Erzählen der Geschichte. Beginne immer, am Anfang mit einem kurzen Satz aus 3-5 Wörtern. Das ist sehr wichtig!!! {text}."
        is_first_interaction = False  
    else:
        prompt = text

    audio_queue = queue.Queue()
    threading.Thread(target=play_audio_from_queue, args=(audio_queue,), daemon=True).start()
    buffer = ""
    response = get_response_from_chatgpt(prompt, conversation_log)
    for event in response:
        event_text = event["choices"][0]["delta"]
        answer = event_text.get("content", "")
        if answer.strip():
            conversation_log.append({"role": "assistant", "content": answer})  
            buffer += answer
            buffer = process_sentences(buffer, audio_queue)

    audio_queue.join()

    audio_queue.put(None)
    return redirect(url_for('narrator'))

def transcribe_audio(file_path):
    start_time = datetime.now()
    segments, _ = model.transcribe(file_path, language="de", beam_size=1, temperature=0, suppress_tokens=None)
    end_time = datetime.now()
    execution_time = end_time - start_time
    transcribed_texts = [segment.text for segment in segments]
    return transcribed_texts, execution_time


def convert_to_audio(sentence):
    start_time = datetime.now()
    audio = generate(text=sentence, voice="flq6f7yk4E4fJM5XTYuZ", model="eleven_multilingual_v1", stream=False)
    end_time = datetime.now()
    print(f"ElevenLabs Audio-Generierungszeit für Satz: '{sentence}' - {end_time - start_time}")
    return audio

audio_processing_completed = False
def play_audio_from_queue(audio_queue):
    redirected = False
    while True:
        if cancellation_flag:
            socketio.emit('change_frontend_cancelled')
            break
        
        audio = audio_queue.get()
        
        if audio is None:
            break
        
        if not redirected:
            socketio.emit('change_frontend_narrator', {'html': 'narrator.html'})
            redirected = True
        
        play(audio)
        audio_queue.task_done()
    redirected = False


    while not audio_queue.empty():
        audio_queue.get()
        audio_queue.task_done()

    
    if not cancellation_flag:
        socketio.emit('change_frontend_user', {'html': 'user.html'})
        print("redirectet zur user.html")



def process_sentences(buffer, audio_queue):
    sentences = re.split(r"(?<=[.!?]) +", buffer)
    for sentence in sentences[:-1]:
        audio = convert_to_audio(sentence)
        audio_queue.put(audio)
    return sentences[-1]


def get_response_from_chatgpt(prompt, conversation_log):
    start_time = datetime.now()
   # response = openai.ChatCompletion.create(model="gpt-4-turbo-preview", messages=conversation_log, temperature=0.66, max_tokens=4000, top_p=1, frequency_penalty=0, presence_penalty=0, stream=True)

    response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=conversation_log, temperature=0.66, max_tokens=100, top_p=1, frequency_penalty=0, presence_penalty=0, stream=True)
    end_time = datetime.now()
    print(f"ChatGPT Antwort-Generierungszeit für Prompt: '{prompt}' - {end_time - start_time}")
    return response


if __name__ == '__main__':
    socketio.run(app)
