import json
import pytz
import re
from time import sleep
from datetime import datetime, date, timedelta, timezone
from dataclasses import dataclass
import sys
import requests
from jinja2 import Environment, BaseLoader
import smtplib
from email.message import EmailMessage
import os


def send_email(subject, body):
    from_email_addr = "t5749837@gmail.com"
    from_email_pass = open("app_password.txt").read().strip()
    to_email_addr = "well1912@gmail.com"
    msg = EmailMessage()

    msg.set_content(body)
    msg['From'] = from_email_addr
    msg['To'] = to_email_addr
    msg['Subject'] = subject

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(from_email_addr, from_email_pass)
    server.send_message(msg)

    server.quit()


@dataclass
class Client:
    last_request: datetime = None
    SLEEP_TIME: int = 5
    cache_file = os.path.join(os.path.abspath(os.path.dirname(__file__)), "grid_cache.json")

    def sleep(self):
        sleep_for = self.SLEEP_TIME - (
            (datetime.now() - self.last_request).microseconds / 1000000
            if self.last_request is not None
            else self.SLEEP_TIME
        )
        self.last_request = datetime.now()
        sleep(sleep_for)

    def get(self, url, retries=3):
        self.sleep()
        print("GET", url)
        result = requests.get(url)
        if retries == 0 or result.status_code < 500:
            return result
        sleep(3)
        print("Retrying")
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
    return start <= target_time <= end


def find_target_value(grid_forecast_list, target_time):
    result = next(filter(lambda t: target_time_occurs_during(t["validTime"], target_time), grid_forecast_list), None)
    if result:
        return result["value"]
    raise ValueError("Can't find forecast", grid_forecast_list, target_time)


def get_message(client, name, lat, lon, grid_attr, threshold, time):
    grid_data = client.forecast_grid_data(lat, lon)
    target_time = (pytz.UTC.localize(datetime.now()) + timedelta(days=1)).replace(**time)
    value = find_target_value(grid_data["properties"]["skyCover"]["values"], target_time)
    if value < threshold:
        return f"{name} will have {grid_attr} of {value} tomorrow at {target_time}"
    return None


locations = [
    ("Deer Lagoon", 47.99282627971839, -122.4832813420477, "skyCover", 50, dict(hour=7, minute=0, second=0)),
    ("Cow Heaven", 48.530990161411246, -121.47828161280614, "skyCover", 50, dict(hour=10, minute=0, second=0)),
    ("Keystone", 48.164146562311, -122.6778767848785, "skyCover", 50, dict(hour=7, minute=0, second=0)),
    ("Mt Erie", 48.454139838938154, -122.62510559151458, "skyCover", 50, dict(hour=7, minute=0, second=0)),
    ("Duckabush", 47.68472641817225, -123.03761998209009, "skyCover", 50, dict(hour=10, minute=0, second=0)),
]


if __name__ == "__main__":
    client = Client()
    messages = list(filter(None, [
        get_message(client, name, lat, lon, grid_attr, threshold, time)
        for name, lat, lon, grid_attr, threshold, time in locations
    ]))
    if messages:
        messages_string = '\n'.join([message for message in messages])
        print("Sending message:")
        print(messages_string)
        send_email("Weather notification", messages_string)
    else:
        print("No locations matching criteria tomorrow")
