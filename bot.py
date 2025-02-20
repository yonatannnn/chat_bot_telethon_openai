import os
import openai
import logging
import time
from telethon import TelegramClient, events
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()
API_ID = os.getenv("API_ID") 
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize OpenAI client and MongoDB
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
client = MongoClient(MONGO_URI)
db = client["chat_bot"]
chat_history_collection = db["chat_history"]
archived_chats_collection = db["archived_chats"]
user_last_message_time = {}
RATE_LIMIT_SECONDS = 2  # Limit to 1 message every 2 seconds per user

# Function to get or create user chat history
def get_user_chat_history(user_id, username):
    user_data = chat_history_collection.find_one({"user_id": user_id})
    if not user_data:
        user_data = {"user_id": user_id, "username": username, "messages": []}
        chat_history_collection.insert_one(user_data)
    else:
        # Ensure the username is updated if it changes
        chat_history_collection.update_one(
            {"user_id": user_id},
            {"$set": {"username": username}}
        )
    return user_data

# Function to archive old chat history
def archive_user_chat_history(user_id, user_name, messages):
    if messages:
        archived_chats_collection.insert_one({
            "user_id": user_id,
            "messages": messages,
            "username": user_name,
            "timestamp": datetime.utcnow()
        })

# Function to update user chat history
def update_user_chat_history(user_id, messages):
    chat_history_collection.update_one(
        {"user_id": user_id},
        {"$set": {"messages": messages}}
    )

# Function to generate a response using OpenAI
def generate_response(user_input, messages):
    conversation = messages + [{"role": "user", "content": user_input}]
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=conversation
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error with OpenAI API: {e}")
        return "Sorry, I encountered an issue while processing your request. Please try again later."

# Initialize Telethon client
bot = TelegramClient("ai_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Command handler for /start
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.reply("Hello! I'm your AI-powered chatbot. Send me a message to start chatting! Use /help to see available commands.")

# Command handler for /help
@bot.on(events.NewMessage(pattern="/help"))
async def help_command(event):
    help_text = """
    Chatbot Commands:
        \n\n/start - Start a conversation
        \n/new - Start a new chat
        \n/help - List available commands
""" 

# Command handler for /new
@bot.on(events.NewMessage(pattern="/new"))
async def new_chat(event):
    user_id = event.sender_id
    username = event.sender.username or event.sender.first_name or "Unknown"
    user_data = get_user_chat_history(user_id, username)
    
    # Archive old chat before resetting
    archive_user_chat_history(user_id, username, user_data["messages"])
    
    update_user_chat_history(user_id, [])  # Reset chat history
    await event.reply("Starting a new conversation! Your old chat has been archived.")

# Message handler for user messages
@bot.on(events.NewMessage)
async def handle_message(event):
    user_id = event.sender_id
    username = event.sender.username or event.sender.first_name or "Unknown"
    user_input = event.text
    current_time = time.time()

    # Ignore commands
    if user_input.startswith("/"):
        return

    # Rate limiting
    if user_id in user_last_message_time:
        if current_time - user_last_message_time[user_id] < RATE_LIMIT_SECONDS:
            await event.reply("⚠️ Please wait a moment before sending another message.")
            return
    user_last_message_time[user_id] = current_time

    # Get user chat history
    user_data = get_user_chat_history(user_id, username)
    messages = user_data["messages"]

    # Indicate bot is typing
    async with bot.action(event.chat_id, "typing"):
        # Generate a response using OpenAI
        bot_response = generate_response(user_input, messages)
    
    # Update chat history
    messages.append({"role": "user", "content": user_input})
    messages.append({"role": "assistant", "content": bot_response})
    update_user_chat_history(user_id, messages)

    # Send the response back to the user
    await event.reply(bot_response)

# Start the bot
if __name__ == "__main__":
    logging.info("Bot is running...")
    bot.run_until_disconnected()
