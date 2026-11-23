import streamlit as st
import ollama
import re
import asyncio
import os
import uuid
import html
from streamlit_mic_recorder import speech_to_text

st.set_page_config(
    page_title="AI Assistant",
    layout="wide",
    initial_sidebar_state="expanded"
)

MODEL_NAME = "llama3.2:1b"

st.markdown("""
<style>

    /* Hide avatar icons completely */
    [data-testid="stChatMessageAvatar"] {
        display: none !important;
    }

    /* Right-aligned pill bubble for user prompts */
    .user-msg-row {
        display: flex;
        justify-content: flex-end;
        margin: 10px 0 14px 0;
    }

    .user-bubble {
        background-color: #eef1f6;
        color: #1f2937;
        padding: 12px 22px;
        border-radius: 24px;
        max-width: 70%;
        font-size: 16px;
        line-height: 1.45;
        word-wrap: break-word;
    }

    /* Clean left-aligned assistant block */
    .stChatMessage {
        background-color: transparent !important;
        border: none !important;
        padding-left: 0 !important;
    }

    [data-testid="stChatMessage"] [data-testid="stButton"] button {
        border-radius: 20px;
        font-size: 14px;
        padding: 2px 14px;
        background-color: #eef0f4;
        border: 1px solid #d1d5db;
        color: #2563eb;
    }

    .main .block-container {
        padding-bottom: 120px;
    }

    .st-key-fixed_chatbar {
        position: fixed;
        bottom: 0;
        left: 21rem;
        right: 0;
        width: auto;
        z-index: 999;
        background-color: #ffffff;
        padding: 12px 25px 15px 25px;
        border-top: 1px solid #e5e7eb;
    }

    [data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
    }

    [data-testid="stTextInput"] input {
        border-radius: 28px;
        padding: 12px 18px;
        font-size: 16px;
        background-color: #eef0f4;
    }

    [data-testid="stForm"] [data-testid="stButton"] button {
        border-radius: 24px;
        height: 46px;
        padding: 0 22px;
        background-color: #2563eb;
        color: white;
        font-weight: 600;
    }

    @media (max-width: 768px) {
        .st-key-fixed_chatbar {
            left: 0;
            width: 100%;
            padding: 10px;
        }

        .user-bubble {
            max-width: 88%;
        }
    }
</style>
""", unsafe_allow_html=True)

if "chats" not in st.session_state:
    st.session_state.chats = {}

if "current_chat" not in st.session_state:
    st.session_state.current_chat = None


def create_new_chat():
    n = 1

    while f"Chat {n}" in st.session_state.chats:
        n += 1

    title = f"Chat {n}"

    st.session_state.chats[title] = []
    st.session_state.current_chat = title


if st.session_state.current_chat is None:
    create_new_chat()

messages = st.session_state.chats[st.session_state.current_chat]

VOICE_MAP = {
    "Male": "en-US-GuyNeural",
    "Female": "en-US-JennyNeural"
}

LENGTH_PROMPTS = {
    "Brief": "Keep your answer very short: 1 to 3 sentences maximum.",
    "Medium": "Give a moderately detailed answer: a short paragraph or a few key points.",
    "Detailed": "Give a thorough, detailed answer with full explanations and examples."
}


def render_user_message(text):
    safe_text = html.escape(text).replace("\n", "<br>")
    st.markdown(
        f'<div class="user-msg-row"><div class="user-bubble">{safe_text}</div></div>',
        unsafe_allow_html=True
    )


def clean_for_speech(text):
    text = re.sub(r'```.*?```', ' code ', text, flags=re.DOTALL)
    text = re.sub(r'[*_`#>|]', '', text)
    text = re.sub(r'\n+', '. ', text)
    return text.strip()


def _edge_tts_bytes(text, gender):
    import edge_tts

    voice = VOICE_MAP.get(gender, VOICE_MAP["Female"])

    async def _generate():
        communicate = edge_tts.Communicate(
            clean_for_speech(text),
            voice
        )

        data = b""

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                data += chunk["data"]

        return data

    return asyncio.run(_generate())


def _pyttsx3_bytes(text, gender):
    import pyttsx3

    engine = pyttsx3.init()
    voices = engine.getProperty("voices")

    chosen = voices[0]

    for voice in voices:
        name = (voice.name or "").lower()

        if gender == "Female" and (
                "female" in name or
                "zira" in name or
                "samantha" in name
        ):
            chosen = voice
            break

        if gender == "Male" and (
                "male" in name or
                "david" in name or
                "mark" in name
        ):
            chosen = voice
            break

    engine.setProperty("voice", chosen.id)

    filename = f"tts_{uuid.uuid4().hex}.mp3"

    engine.save_to_file(
        clean_for_speech(text),
        filename
    )

    engine.runAndWait()

    with open(filename, "rb") as file:
        audio_data = file.read()

    os.remove(filename)

    return audio_data


def text_to_speech_bytes(text, gender):
    try:
        return _edge_tts_bytes(text, gender)

    except Exception:
        return _pyttsx3_bytes(text, gender)


with st.sidebar:
    if st.button(
            "New Chat",
            use_container_width=True,
            type="primary"
    ):
        create_new_chat()
        st.rerun()

    st.divider()

    st.subheader("Settings")

    voice_gender = st.selectbox(
        "Voice",
        ["Male", "Female"],
        index=1,
        key="voice_gender"
    )

    response_length = st.selectbox(
        "Response Length",
        ["Brief", "Medium", "Detailed"],
        index=1,
        key="response_length"
    )

    auto_speak = st.toggle(
        "Auto-read responses",
        value=False,
        key="auto_speak",
        help="Automatically speak every new AI response."
    )

    st.divider()

    if st.button(
            "Clear current chat",
            use_container_width=True
    ):
        st.session_state.chats[
            st.session_state.current_chat
        ] = []

        st.rerun()

    st.divider()

    st.subheader("History")

    has_questions = False

    for chat_title, chat_messages in st.session_state.chats.items():

        user_questions = [
            msg["content"]
            for msg in chat_messages
            if msg["role"] == "user"
        ]

        if user_questions:
            has_questions = True

            st.markdown(f"**{chat_title}**")

            for question in user_questions:
                st.write(f"• {question}")

    if not has_questions:
        st.caption("No questions asked yet.")

    st.divider()

    st.caption("Llama 3.2 1B | Ollama | Streamlit")
    st.caption("Conversation is stored in the current session.")

st.title("AI ASSISTANT ")
st.write("A conversational assistant with text interaction, voice input,and spoken AI responses")
st.divider()

if not messages:
    st.markdown("### Welcome")

    st.write(
        "Hello! I am your AI Voice Assistant. "
        "Ask me anything by typing or using voice input, and I will help you."
    )

    st.markdown("### What can I help you with?")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.info("**Programming**\n\nPython, Java, HTML and more.")

    with col2:
        st.info("**Education**\n\nLearning, explanations and concepts.")

    with col3:
        st.info("**Ideas**\n\nCreative ideas and problem solving.")

for idx, message in enumerate(messages):

    if message["role"] == "user":
        render_user_message(message["content"])

    else:
        with st.chat_message("assistant", avatar=None):

            st.markdown(message["content"])

            if st.button(
                    "Listen",
                    key=f"listen_{idx}"
            ):

                try:
                    audio = text_to_speech_bytes(
                        message["content"],
                        voice_gender
                    )

                    st.audio(
                        audio,
                        format="audio/mp3",
                        autoplay=True
                    )

                except Exception as e:
                    st.error("Speech generation failed.")
                    st.code(str(e))


def generate_response(model_messages):
    response = ollama.chat(
        model=MODEL_NAME,
        messages=model_messages,
        stream=True,
        options={
            "temperature": 0.7
        }
    )

    for chunk in response:

        content = chunk.get(
            "message", {}
        ).get("content", "")

        if content:
            yield content


voice_text = None
typed_prompt = ""
send = False

with st.container(key="fixed_chatbar"):
    mic_col, chat_col = st.columns([1, 12])

    with mic_col:
        voice_text = speech_to_text(
            language="en",
            start_prompt=" Speak ",
            stop_prompt=" Stop ",
            just_once=True,
            key="mic_input"
        )

    with chat_col:
        with st.form(
                "chat_form",
                clear_on_submit=True,
                border=False
        ):
            input_col, btn_col = st.columns([11, 1])

            with input_col:
                typed_prompt = st.text_input(
                    "chat",
                    placeholder="Ask me anything...",
                    label_visibility="collapsed"
                )

            with btn_col:
                send = st.form_submit_button(
                    "Send",
                    use_container_width=True
                )

user_prompt = None

if voice_text:
    user_prompt = voice_text.strip()

elif send and typed_prompt.strip():
    user_prompt = typed_prompt.strip()

if user_prompt:

    if (
            len(messages) == 0
            and st.session_state.current_chat.startswith("Chat ")
    ):

        new_title = user_prompt[:30]

        if new_title in st.session_state.chats:
            new_title = (
                f"{new_title} "
                f"({len(st.session_state.chats)})"
            )

        st.session_state.chats[new_title] = (
            st.session_state.chats.pop(
                st.session_state.current_chat
            )
        )

        st.session_state.current_chat = new_title

        messages = st.session_state.chats[new_title]

    messages.append({
        "role": "user",
        "content": user_prompt
    })

    render_user_message(user_prompt)

    with st.chat_message("assistant", avatar=None):

        try:

            model_messages = [
                                 {
                                     "role": "system",
                                     "content": LENGTH_PROMPTS[response_length]
                                 }
                             ] + messages

            with st.spinner("Thinking..."):

                response = st.write_stream(
                    generate_response(model_messages)
                )

            messages.append({
                "role": "assistant",
                "content": response
            })

            if response:

                if st.button(
                        "Listen",
                        key=f"listen_new_{uuid.uuid4().hex}"
                ):

                    try:
                        audio = text_to_speech_bytes(
                            response,
                            voice_gender
                        )

                        st.audio(
                            audio,
                            format="audio/mp3",
                            autoplay=True
                        )

                    except Exception as e:
                        st.error("Speech generation failed.")
                        st.code(str(e))

            if auto_speak and response:

                try:
                    audio = text_to_speech_bytes(
                        response,
                        voice_gender
                    )

                    st.audio(
                        audio,
                        format="audio/mp3",
                        autoplay=True
                    )

                except Exception as e:
                    st.error("Automatic speech generation failed.")
                    st.code(str(e))

        except ollama.ResponseError as e:

            st.error(f"Ollama model error: {e}")

        except Exception as e:

            st.error(
                "Unable to connect to Ollama. "
                "Please ensure Ollama is running "
                "and the model is installed."
            )

            st.code(str(e))

st.divider()

st.markdown(
    """
    <center>
        <p style="color:gray;">
            AI Voice Assistant |
            Built with Python and Streamlit |
            Powered by Ollama
        </p>
    </center>
    """,
    unsafe_allow_html=True
)