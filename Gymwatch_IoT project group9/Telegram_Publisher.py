import telepot
from telepot.loop import MessageLoop
import requests
import time
from datetime import datetime
from MyMQTT import MyMQTT
import random
import threading
import json


class SensorPublisher:
    def __init__(self, clientID, broker, port, topic, username, password, telegram_bot_token):
        self.client_mqtt = MyMQTT(clientID, broker, port, self)
        self.client_mqtt.start()
        self.topic = topic
        self.device_active = False

        self.msg = {
            "bn": clientID,
            "e": [
                {"n": "Heart Rate Sensor", "u": "bpm", "t": None, "v": None},
                {"n": "Accelerometer", "u": "m/s²", "t": None, "v": None},
                {"n": "Gyroscope", "u": "°/s", "t": None, "v": None},
                {"n": "Stress Sensor", "u": "HRV", "t": None, "v": None},
                {"n": "Respiratory Rate Sensor", "u": "rpm", "t": None, "v": None},
                {"n": "Inclinometer", "u": "Degrees", "t": None, "v": None},
                {"n": "Exercise", "u": "none", "t": None, "v": None},
                {"n": "Series", "u": "none", "t": None, "v": None},
                {"n": "Weight", "u": "kg", "t": None, "v": None}
            ]
        }

        self.thingspeak_url = 'https://api.thingspeak.com/update'
        self.thingspeak_api_key = 'PSR7PTZ3BH96VJFP'

        self.bot = telepot.Bot(telegram_bot_token)
        self.state = "idle"
        self.current_chat_id = None

        self.exercise = ""
        self.set_count = 0
        self.total_sets = 0
        self.current_set = 0
        self.weight = 0
        self.rest_time = 0
        self.send_delay = 20  # seconds

        self.batch = []  # Buffer per accumulare i dati attuali del batch
        self.batch_lock = threading.Lock()  # Blocco per proteggere l'accesso al batch
        self.sending_thread = threading.Thread(target=self.send_data_from_batch)
        self.sending_thread.start()

        self.food_data = []  # Lista per tenere traccia dei pasti
        self.food_log_file = "food_log.txt"  # File per salvare i dati dei pasti

    def handle_message(self, msg):
        content_type, chat_type, chat_id = telepot.glance(msg)
        text = msg["text"].strip().lower()

        print(f"Received message: {text} from chat_id: {chat_id}")

        self.current_chat_id = chat_id

        state_handlers = {
            "idle": self.handle_idle,
            "confirm_start": self.handle_confirm_start,
            "waiting_for_exercise": self.handle_waiting_for_exercise,
            "waiting_for_sets": self.handle_waiting_for_sets,
            "waiting_for_rest_time": self.handle_waiting_for_rest_time,
            "waiting_for_weight": self.handle_waiting_for_weight,
            "confirm_ready": self.handle_confirm_ready,
            "continue_workout": self.handle_continue_workout,
            "waiting_for_food_name": self.handle_waiting_for_food_name,
            "waiting_for_quantity": self.handle_waiting_for_quantity,
            "waiting_for_macros": self.handle_waiting_for_macros,
            "waiting_for_kcal": self.handle_waiting_for_kcal
        }

        if self.state in state_handlers:
            state_handlers[self.state](text)
        else:
            self.send_message_to_telegram("Unexpected input. Please follow the prompts.")

    def handle_idle(self, text):
        if text == "/start":
            self.send_message_to_telegram("Welcome! Do you want to start a workout (/train) or log a meal (/food)?")
            self.state = "idle"
        elif text == "/train":
            self.send_message_to_telegram("Great! Please enter the name of the exercise.")
            self.state = "waiting_for_exercise"
        elif text == "/food":
            self.send_message_to_telegram("What food did you eat?")
            self.state = "waiting_for_food_name"

    def handle_confirm_start(self, text):
        if text == "y":
            self.send_message_to_telegram("Great! Please enter the name of the exercise.")
            self.state = "waiting_for_exercise"
        elif text == "n":
            self.send_message_to_telegram("Let me know when you're ready.")
        else:
            self.send_message_to_telegram("Please enter 'Y' for Yes or 'N' for No.")

    # Gestione delle funzioni per l'allenamento
    def handle_waiting_for_exercise(self, text):
        self.exercise = text
        self.send_message_to_telegram("How many sets do you want to do?")
        self.state = "waiting_for_sets"

    def handle_waiting_for_sets(self, text):
        try:
            self.total_sets = int(text)
            if self.total_sets <= 0:
                raise ValueError
            self.send_message_to_telegram("Enter the rest time between sets (seconds):")
            self.state = "waiting_for_rest_time"
        except ValueError:
            self.send_message_to_telegram("Please enter a valid positive number for sets.")

    def handle_waiting_for_rest_time(self, text):
        try:
            self.rest_time = int(text)
            if self.rest_time < 0:
                raise ValueError
            self.send_message_to_telegram("Enter the weight used for each set (kg):")
            self.state = "waiting_for_weight"
        except ValueError:
            self.send_message_to_telegram("Please enter a valid positive number for rest time.")

    def handle_waiting_for_weight(self, text):
        try:
            self.weight = float(text)
            if self.weight <= 0:
                raise ValueError
            self.send_message_to_telegram("Are you ready to start the first set? (Y/N)")
            self.state = "confirm_ready"
        except ValueError:
            self.send_message_to_telegram("Please enter a valid positive number for the weight.")

    def handle_confirm_ready(self, text):
        if text == "y":
            self.current_set = 0
            self.device_active = True
            self.run_workout()
        elif text == "n":
            self.send_message_to_telegram("Let me know when you're ready.")
        else:
            self.send_message_to_telegram("Please enter 'Y' for Yes or 'N' for No.")

    def handle_continue_workout(self, text):
        if text == "y":
            self.send_message_to_telegram("Great! Please enter the name of the next exercise.")
            self.state = "waiting_for_exercise"
        elif text == "n":
            self.send_message_to_telegram("Workout session ended. Continuing to send data from the batch.")
            self.state = "idle"
        else:
            self.send_message_to_telegram("Please enter 'Y' for Yes or 'N' for No.")

    # Gestione delle funzioni per la dieta
    def handle_waiting_for_food_name(self, text):
        self.current_food = {"food": text, "date": datetime.now().strftime("%Y-%m-%d")}
        self.send_message_to_telegram("What quantity did you eat (in grams)?")
        self.state = "waiting_for_quantity"

    def handle_waiting_for_quantity(self, text):
        try:
            self.current_food["quantity"] = float(text)
            self.send_message_to_telegram("Carbs per 100g?")
            self.state = "waiting_for_macros"
            self.macro_step = "carbs"
        except ValueError:
            self.send_message_to_telegram("Please enter a valid number for the quantity.")

    def handle_waiting_for_macros(self, text):
        try:
            value = float(text)
            if value < 0:
                raise ValueError
            if self.macro_step == "carbs":
                self.current_food["carbs"] = value * (self.current_food["quantity"] / 100)
                self.send_message_to_telegram("Fats per 100g?")
                self.macro_step = "fats"
            elif self.macro_step == "fats":
                self.current_food["fats"] = value * (self.current_food["quantity"] / 100)
                self.send_message_to_telegram("Proteins per 100g?")
                self.macro_step = "proteins"
            elif self.macro_step == "proteins":
                self.current_food["proteins"] = value * (self.current_food["quantity"] / 100)
                self.send_message_to_telegram("Calories per 100g?")
                self.state = "waiting_for_kcal"
        except ValueError:
            self.send_message_to_telegram(f"Please enter a valid number for {self.macro_step} per 100g.")

    def handle_waiting_for_kcal(self, text):
        try:
            kcal_per_100g = float(text)
            if kcal_per_100g < 0:
                raise ValueError
            self.current_food["kcal"] = kcal_per_100g * (self.current_food["quantity"] / 100)
            self.save_food_log(self.current_food)
            self.send_message_to_telegram(f"Food logged: {self.current_food}")
            self.state = "idle"
        except ValueError:
            self.send_message_to_telegram("Please enter a valid number for calories per 100g.")

    def save_food_log(self, food_data):
        """Salva i dati del pasto in un file di testo."""
        try:
            with open(self.food_log_file, "a") as file:
                file.write(json.dumps(food_data) + "\n")
        except IOError as e:
            print(f"Error writing to file: {e}")

    def send_message_to_telegram(self, message):
        if not self.current_chat_id:
            print("No active chat found.")
            return

        try:
            self.bot.sendMessage(self.current_chat_id, message)
            print(f"Message sent to Telegram chat {self.current_chat_id}: {message}")
        except telepot.exception.TelegramError as e:
            print(f"Failed to send message to chat {self.current_chat_id}: {e}")

    # Funzioni per l'allenamento e gestione dati MQTT rimangono invariate
    def generate_acceleration(self):
        x = random.uniform(-2.0, 2.0)
        y = random.uniform(-2.0, 2.0)
        z = random.uniform(9.0, 11.0)
        magnitude = (x**2 + y**2 + z**2)**0.5
        return {"x": x, "y": y, "z": z, "magnitude": magnitude}

    def send_data_to_thingspeak(self, data, retries=5):
        for attempt in range(retries):
            try:
                response = requests.get(self.thingspeak_url, params=data)
                response.raise_for_status()
                if response.text == '0':
                    print(f'Error: Data not accepted by ThingSpeak. Attempt {attempt + 1} of {retries}.')
                else:
                    print('Data successfully sent to ThingSpeak!')
                    return True
            except requests.exceptions.RequestException as err:
                print(f'Error sending data to ThingSpeak: {err}. Attempt {attempt + 1} of {retries}.')
                time.sleep(2 ** attempt)
        print('Failed to send data after several attempts.')
        return False

    def send_data_from_batch(self):
        """Invia i dati dal batch con ritardo tra ogni invio."""
        while True:
            time.sleep(self.send_delay)
            with self.batch_lock:
                if self.batch:
                    data = self.batch.pop(0)
                    print(f"Sending data to ThingSpeak: {data}")
                    self.send_data_to_thingspeak(data)

    def run_workout(self):
        while self.current_set < self.total_sets:
            if not self.device_active:
                break

            self.current_set += 1
            print(f"Starting set {self.current_set}/{self.total_sets}")

            # Genera i dati del sensore e aggiorna il messaggio
            self.msg["e"][0]["t"] = datetime.now().isoformat()
            self.msg["e"][0]["v"] = random.uniform(60, 100)
            self.msg["e"][1].update(self.generate_acceleration())
            self.msg["e"][2]["v"] = random.uniform(0, 100)
            self.msg["e"][3]["v"] = random.uniform(10, 100)
            self.msg["e"][4]["v"] = random.uniform(10, 30)
            self.msg["e"][5]["v"] = random.uniform(0, 90)
            self.msg["e"][6]["v"] = self.exercise
            self.msg["e"][7]["v"] = self.current_set
            self.msg["e"][8]["v"] = self.weight

            # Aggiungi i dati al batch per ThingSpeak
            data = {
                'api_key': self.thingspeak_api_key,
                'field1': self.msg["e"][0]["v"],  # Heart Rate
                'field2': self.msg["e"][1]["magnitude"],  # Acceleration magnitude
                'field3': self.msg["e"][2]["v"],  # Gyroscope
                'field4': self.msg["e"][3]["v"],  # Stress Sensor
                'field5': self.msg["e"][4]["v"],  # Respiratory Rate
                'field6': self.msg["e"][5]["v"],  # Inclination
                'field7': self.current_set,       # Set Number
                'field8': self.exercise           # Exercise Name
            }

            with self.batch_lock:
                self.batch.append(data)

            print(f"Set {self.current_set} completed. Resting for {self.rest_time} seconds.")
            time.sleep(self.rest_time)

        self.device_active = False
        self.send_message_to_telegram("Workout session completed.")
        self.send_message_to_telegram("Do you want to continue with another exercise? (Y/N)")
        self.state = "continue_workout"

    def handle_mqtt_message(self, topic, message):
        print(f"MQTT message received on topic {topic}: {message}")

    def on_message(self, topic, message):
        self.handle_mqtt_message(topic, message)

    def stop_sending_thread(self):
        self.sending_thread.join()

    def start(self):
        MessageLoop(self.bot, self.handle_message).run_as_thread()
        print("Bot is listening... Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Bot stopped.")
        finally:
            self.stop_sending_thread()


if __name__ == "__main__":
    clientID = "EgoEGjcflBEJFhQnGSoeOTA"
    broker = "mqtt.thingspeak.com"
    port = 1883
    topic = "channels/YOUR_CHANNEL_ID/publish"
    username = "EgoEGjcflBEJFhQnGSoeOTA"
    password = "SyG+R0Qy+bpAyMgmqhbVRxq9"
    telegram_bot_token = "7545231459:AAFDAqrmdlXRpW2eCrbGErLct0juWhwWcWU"

    publisher = SensorPublisher(clientID, broker, port, topic, username, password, telegram_bot_token)
    publisher.start()

