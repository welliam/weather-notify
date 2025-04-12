import json
import pytz
import re
from time import sleep
from datetime import datetime, timedelta
from dataclasses import dataclass
import sys
import requests
import smtplib
from email.message import EmailMessage
import os
import logging
import suntime


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def send_email(subject, body):
    from_email_addr = "t5749837@gmail.com"
    try:
        from_email_pass = (
            open(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "app_password.txt"
                )
            )
            .read()
            .strip()
        )
    except FileNotFoundError:
        logging.warning("No app password found, not sending email")
        return
    to_email_addr = "well1912@gmail.com"
    msg = EmailMessage()

    msg.set_content(body)
    msg["From"] = from_email_addr
    msg["To"] = to_email_addr
    msg["Subject"] = subject

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(from_email_addr, from_email_pass)
    server.send_message(msg)

    server.quit()


@dataclass
class Client:
    last_request: datetime = None
    SLEEP_TIME: int = int(os.getenv("SLEEP", "10"))
    cache_file = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "grid_cache.json"
    )

    def sleep(self):
        if self.SLEEP_TIME:
            sleep_for = self.SLEEP_TIME - (
                (datetime.now() - self.last_request).microseconds / 1000000
                if self.last_request is not None
                else self.SLEEP_TIME
            )
            self.last_request = datetime.now()
            sleep(sleep_for)

    def get(self, url, retries=3):
        self.sleep()
        result = requests.get(url)

        if retries == 0 or result.status_code < 500:
            return result

        sleep(self.SLEEP_TIME)
        logging.debug("Retrying")
        return self.get(url, retries - 1)

    def _get_grid(self, lat, lon):
        if not os.path.exists(self.cache_file):
            json.dump({}, open(self.cache_file, "w"))

        cache = json.load(open(self.cache_file))
        key = f"{lat},{lon}"
        if key in cache:
            return cache[key]

        points = f"https://api.weather.gov/points/{lat},{lon}"
        points_result = self.get(points).json()
        grid_url = points_result["properties"]["forecastGridData"]
        cache[key] = grid_url
        json.dump(cache, open(self.cache_file, "w"))
        return cache[key]

    def forecast_grid_data(self, lat, lon):
        return self.get(self._get_grid(lat, lon)).json()


def duration_to_start_end(duration_str: str):
    [dt, duration] = duration_str.split("/")
    start = datetime.fromisoformat(dt)
    if hours := re.match("PT([0-9]+)H", duration).groups():
        return [start, start + timedelta(hours=int(hours[0]))]
    raise ValueError("Weird duration_str", duration_str)


def target_time_occurs_during(duration_str: str, target_time: datetime):
    [start, end] = duration_to_start_end(duration_str)
    return start <= target_time < end


def find_target_value(grid_forecast_list, target_time):
    result = next(
        filter(
            lambda t: target_time_occurs_during(t["validTime"], target_time),
            grid_forecast_list,
        ),
        None,
    )
    if result:
        return result["value"]
    raise ValueError("Can't find forecast", grid_forecast_list, target_time)


@dataclass
class Condition:
    grid_attr: str
    threshold: int


@dataclass
class Message:
    name: str
    conditions: list[Condition]
    values: dict[str, int]
    target_time: datetime

    @property
    def message(self):
        time = self.target_time.astimezone(pytz.timezone("US/Pacific"))
        parts = []
        for condition in self.conditions:
            unit = "mph" if condition.grid_attr == "windSpeed" else "%"
            parts.append(
                f"{condition.grid_attr} of {self.values[condition.grid_attr]}{unit}"
            )
        return f"{self.name} will have {' and '.join(parts)} tomorrow at {time.strftime('%H:%M')}"

    @property
    def meets_criteria(self):
        return all(
            self.values[condition.grid_attr] < condition.threshold
            for condition in self.conditions
        )


def get_message(client, name, lat, lon, conditions, time):
    grid_data = client.forecast_grid_data(lat, lon)
    target_time = get_time(time, lat, lon)
    values = {}
    for condition in conditions:
        values[condition.grid_attr] = find_target_value(
            grid_data["properties"][condition.grid_attr]["values"], target_time
        )
    return Message(
        name=name, conditions=conditions, values=values, target_time=target_time
    )


def get_time(time, lat, lon):
    if isinstance(time, dict):
        return (pytz.UTC.localize(datetime.now()) + timedelta(days=1)).replace(**time)
    if time == "sunrise":
        return suntime.Sun(lat, lon).get_sunrise_time() + timedelta(days=1)
    else:
        raise ValueError("idk how to handle", time)


locations = [
    (
        "Deer Lagoon",
        47.99282627971839,
        -122.4832813420477,
        [Condition("skyCover", 60), Condition("windSpeed", 10)],
        "sunrise",
    ),
    (
        "Keystone",
        48.164146562311,
        -122.6778767848785,
        [Condition("skyCover", 60), Condition("windSpeed", 10)],
        "sunrise",
    ),
    (
        "Mt Erie",
        48.454139838938154,
        -122.62510559151458,
        [Condition("skyCover", 60), Condition("windSpeed", 10)],
        "sunrise",
    ),
]


if __name__ == "__main__":
    client = Client()
    messages = [
        get_message(client, name, lat, lon, conditions, time)
        for name, lat, lon, conditions, time in locations
    ]
    messages_meeting_criteria = [
        message for message in messages if message.meets_criteria
    ]
    for message in messages:
        logging.info(message.message)

    if messages_meeting_criteria:
        message_string = "\n".join(
            [message.message for message in messages_meeting_criteria]
        )
        subject = "Weather notification: " + ", ".join(
            [message.name for message in messages_meeting_criteria]
        )
        logging.debug(f"Sending message")
        send_email(subject, message_string)
    else:
        logging.info("No locations matching criteria tomorrow")
