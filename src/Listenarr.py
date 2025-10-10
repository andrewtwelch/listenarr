import json
import logging
import os
import random
import string
import threading
from flask import Flask, render_template
from flask_socketio import SocketIO
import requests
import musicbrainzngs
from unidecode import unidecode

class DataHandler:
    def __init__(self):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.lidify_logger = logging.getLogger()
        self.musicbrainzngs_logger = logging.getLogger("musicbrainzngs")
        self.musicbrainzngs_logger.setLevel("WARNING")
        self.pylast_logger = logging.getLogger("pylast")
        self.pylast_logger.setLevel("WARNING")

        app_name_text = os.path.basename(__file__).replace(".py", "")
        release_version = os.environ.get("RELEASE_VERSION", "unknown")
        self.lidify_logger.warning(f"{'*' * 50}\n")
        self.lidify_logger.warning(f"{app_name_text} Version: {release_version}\n")
        self.lidify_logger.warning(f"{'*' * 50}")

        self.search_in_progress_flag = False
        self.new_found_artists_counter = 0
        self.clients_connected_counter = 0
        self.config_folder = "config"
        self.recommended_artists = []
        self.lidarr_items = []
        self.lidarr_mbids = []
        self.cleaned_lidarr_items = []
        self.stop_event = threading.Event()
        self.stop_event.set()
        if not os.path.exists(self.config_folder):
            os.makedirs(self.config_folder)
        self.load_environ_or_config_settings()
        if self.auto_start:
            try:
                auto_start_thread = threading.Timer(self.auto_start_delay, self.automated_startup)
                auto_start_thread.daemon = True
                auto_start_thread.start()

            except Exception as e:
                self.lidify_logger.error(f"Auto Start Error: {str(e)}")

    def load_environ_or_config_settings(self):
        # Defaults
        default_settings = {
            "lidarr_address": "http://192.168.1.2:8686",
            "lidarr_api_key": "",
            "root_folder_path": "/data/media/music/",
            "fallback_to_top_result": False,
            "lidarr_api_timeout": 120.0,
            "quality_profile_id": 1,
            "metadata_profile_id": 1,
            "search_for_missing_albums": False,
            "dry_run_adding_to_lidarr": False,
            "app_name": "Lidify",
            "app_rev": "0.10",
            "app_url": "http://" + "".join(random.choices(string.ascii_lowercase, k=10)) + ".com",
            "last_fm_api_key": "",
            "last_fm_api_secret": "",
            "mode": "ListenBrainz",
            "auto_start": False,
            "auto_start_delay": 60,
        }

        # Load settings from environmental variables (which take precedence) over the configuration file.
        self.lidarr_address = os.environ.get("lidarr_address", "")
        self.lidarr_api_key = os.environ.get("lidarr_api_key", "")
        self.root_folder_path = os.environ.get("root_folder_path", "")
        fallback_to_top_result = os.environ.get("fallback_to_top_result", "")
        self.fallback_to_top_result = fallback_to_top_result.lower() == "true" if fallback_to_top_result != "" else ""
        lidarr_api_timeout = os.environ.get("lidarr_api_timeout", "")
        self.lidarr_api_timeout = float(lidarr_api_timeout) if lidarr_api_timeout else ""
        quality_profile_id = os.environ.get("quality_profile_id", "")
        self.quality_profile_id = int(quality_profile_id) if quality_profile_id else ""
        metadata_profile_id = os.environ.get("metadata_profile_id", "")
        self.metadata_profile_id = int(metadata_profile_id) if metadata_profile_id else ""
        search_for_missing_albums = os.environ.get("search_for_missing_albums", "")
        self.search_for_missing_albums = search_for_missing_albums.lower() == "true" if search_for_missing_albums != "" else ""
        dry_run_adding_to_lidarr = os.environ.get("dry_run_adding_to_lidarr", "")
        self.dry_run_adding_to_lidarr = dry_run_adding_to_lidarr.lower() == "true" if dry_run_adding_to_lidarr != "" else ""
        self.app_name = os.environ.get("app_name", "")
        self.app_rev = os.environ.get("app_rev", "")
        self.app_url = os.environ.get("app_url", "")
        self.last_fm_api_key = os.environ.get("last_fm_api_key", "")
        self.last_fm_api_secret = os.environ.get("last_fm_api_secret", "")
        self.mode = os.environ.get("mode", "")
        auto_start = os.environ.get("auto_start", "")
        self.auto_start = auto_start.lower() == "true" if auto_start != "" else ""
        auto_start_delay = os.environ.get("auto_start_delay", "")
        self.auto_start_delay = float(auto_start_delay) if auto_start_delay else ""

        # Load variables from the configuration file if not set by environmental variables.
        try:
            self.settings_config_file = os.path.join(self.config_folder, "settings_config.json")
            if os.path.exists(self.settings_config_file):
                self.lidify_logger.info(f"Loading Config via file")
                with open(self.settings_config_file, "r") as json_file:
                    ret = json.load(json_file)
                    for key in ret:
                        if getattr(self, key) == "":
                            setattr(self, key, ret[key])
        except Exception as e:
            self.lidify_logger.error(f"Error Loading Config: {str(e)}")

        # Load defaults if not set by an environmental variable or configuration file.
        for key, value in default_settings.items():
            if getattr(self, key) == "":
                setattr(self, key, value)

        # Save config.
        self.save_config_to_file()

    def automated_startup(self):
        self.get_artists_from_lidarr(checked=True)
        artists = [x["mbid"] for x in self.lidarr_items]
        self.start(artists)

    def connection(self):
        if self.recommended_artists:
            socketio.emit("more_artists_loaded", self.recommended_artists)
        self.clients_connected_counter += 1

    def disconnection(self):
        self.clients_connected_counter = max(0, self.clients_connected_counter - 1)

    def start(self, data):
        try:
            socketio.emit("clear")
            self.new_found_artists_counter = 1
            self.artists_to_use_in_search = []
            self.recommended_artists = []

            for item in self.lidarr_items:
                item_mbid = item["mbid"]
                if item_mbid in data:
                    item["checked"] = True
                    self.artists_to_use_in_search.append(item["mbid"])
                else:
                    item["checked"] = False

            if self.artists_to_use_in_search:
                self.stop_event.clear()
            else:
                self.stop_event.set()
                raise Exception("No Lidarr Artists Selected")

        except Exception as e:
            self.lidify_logger.error(f"Statup Error: {str(e)}")
            self.stop_event.set()
            ret = {"Status": "Error", "Code": str(e), "Data": self.lidarr_items, "Running": not self.stop_event.is_set()}
            socketio.emit("lidarr_sidebar_update", ret)

        else:
            self.find_similar_artists()

    def get_artists_from_lidarr(self, checked=False):
        try:
            self.lidify_logger.info(f"Getting Artists from Lidarr")
            self.lidarr_items = []
            self.lidarr_mbids = []
            endpoint = f"{self.lidarr_address}/api/v1/artist"
            headers = {"X-Api-Key": self.lidarr_api_key}
            response = requests.get(endpoint, headers=headers, timeout=self.lidarr_api_timeout)

            if response.status_code == 200:
                self.full_lidarr_artist_list = response.json()
                self.lidarr_items = [{"name": unidecode(artist["artistName"], replace_str=" "), "mbid": artist["foreignArtistId"], "checked": checked} for artist in self.full_lidarr_artist_list]
                self.lidarr_mbids = [artist["foreignArtistId"] for artist in self.full_lidarr_artist_list]
                self.lidarr_items.sort(key=lambda x: x["name"].lower())
                self.cleaned_lidarr_items = [item["name"].lower() for item in self.lidarr_items]
                status = "Success"
                data = self.lidarr_items
            else:
                status = "Error"
                data = response.text

            ret = {"Status": status, "Code": response.status_code if status == "Error" else None, "Data": data, "Running": not self.stop_event.is_set()}

        except Exception as e:
            self.lidify_logger.error(f"Getting Artist Error: {str(e)}")
            ret = {"Status": "Error", "Code": 500, "Data": str(e), "Running": not self.stop_event.is_set()}

        finally:
            socketio.emit("lidarr_sidebar_update", ret)

    def filter_similar_artist_response(self, suggested_artist):
        return suggested_artist["artist_mbid"] not in self.lidarr_mbids

    def find_similar_artists(self):
        if self.stop_event.is_set() or self.search_in_progress_flag:
            return
        else:
            try:
                self.lidify_logger.info("Searching for new artists via ListenBrainz similar-artists")
                self.search_in_progress_flag = True
                payload = [
                    {
                        "artist_mbids": self.artists_to_use_in_search,
                        "algorithm": f"session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
                    }
                ]
                similar_artists = requests.post("https://labs.api.listenbrainz.org/similar-artists/json", json=payload).json()
                if len(similar_artists) == 0:
                    socketio.emit("new_toast_msg", {"title": "No similar artists", "message": f"No similar artists found."})
                    raise Exception("No similar artists returned")
                filtered_similar_artists = filter(self.filter_similar_artist_response, similar_artists)

                for artist in filtered_similar_artists:
                    if self.stop_event.is_set():
                        break
                    try:
                        payload = {
                            "artist_mbids": [artist["artist_mbid"]]
                        }
                        returned_artist = {
                            "Name": artist["name"],
                            "Mbid": artist["artist_mbid"],
                            "Status": "",
                            "Similar_To": ""
                        }
                        for lidarr_artist in self.lidarr_items:
                            if lidarr_artist["mbid"] == artist["reference_mbid"]:
                                returned_artist["Similar_To"] = f"Similar to {lidarr_artist["name"]}"
                                break

                        stage = "ListenBrainz artist popularity lookup"
                        popularity_data = requests.post("https://api.listenbrainz.org/1/popularity/artist", json=payload).json()
                        returned_artist["Popularity"] = f"{self.format_numbers(popularity_data[0]["total_listen_count"])} listens"
                        returned_artist["Followers"] = f"{self.format_numbers(popularity_data[0]["total_user_count"])} users"

                        stage = "Send to client"
                        self.recommended_artists.append(returned_artist)
                        socketio.emit("more_artists_loaded", [returned_artist])

                    except Exception as e:
                        self.lidify_logger.error(f"{stage} error: {str(e)}")

            except Exception as e:
                self.lidify_logger.error(f"ListenBrainz similar-artists lookup error: {str(e)}")

            finally:
                self.search_in_progress_flag = False

    def add_artists(self, mbid):
        try:
            musicbrainzngs.set_useragent(self.app_name, self.app_rev, self.app_url)
            artist_lookup = musicbrainzngs.get_artist_by_id(mbid)
            artist_details = artist_lookup["artist"]
            artist_name = artist_details["name"]
            artist_folder = artist_name.replace("/", " ")

            lidarr_url = f"{self.lidarr_address}/api/v1/artist"
            headers = {"X-Api-Key": self.lidarr_api_key}
            payload = {
                "ArtistName": artist_name,
                "qualityProfileId": self.quality_profile_id,
                "metadataProfileId": self.metadata_profile_id,
                #"path": os.path.join(self.root_folder_path, artist_folder, ""),
                "rootFolderPath": self.root_folder_path,
                "foreignArtistId": mbid,
                "monitored": True,
                "addOptions": {"searchForMissingAlbums": self.search_for_missing_albums},
            }
            if self.dry_run_adding_to_lidarr:
                response = requests.Response()
                response.status_code = 201
            else:
                response = requests.post(lidarr_url, headers=headers, json=payload)

            if response.status_code == 201:
                self.lidify_logger.info(f"Artist '{artist_name}' added successfully to Lidarr.")
                status = "Added"
                self.lidarr_items.append({"name": artist_name, "checked": False})
                self.cleaned_lidarr_items.append(unidecode(artist_name).lower())
            else:
                self.lidify_logger.error(f"Failed to add artist '{artist_name}' to Lidarr.")
                error_data = json.loads(response.content)
                error_message = error_data[0].get("errorMessage", "No Error Message Returned") if error_data else "Error Unknown"
                self.lidify_logger.error(error_message)
                if "already been added" in error_message:
                    status = "Already in Lidarr"
                    self.lidify_logger.info(f"Artist '{artist_name}' is already in Lidarr.")
                elif "configured for an existing artist" in error_message:
                    status = "Already in Lidarr"
                    self.lidify_logger.info(f"'{artist_folder}' folder already configured for an existing artist.")
                elif "Invalid Path" in error_message:
                    status = "Invalid Path"
                    self.lidify_logger.info(f"Path: {os.path.join(self.root_folder_path, artist_folder, '')} not valid.")
                else:
                    status = "Failed to Add"

            for item in self.recommended_artists:
                if item["Name"] == artist_name:
                    item["Status"] = status
                    socketio.emit("refresh_artist", item)
                    break

        except Exception as e:
            self.lidify_logger.error(f"Adding Artist Error: {str(e)}")

    def load_settings(self):
        try:
            data = {
                "lidarr_address": self.lidarr_address,
                "lidarr_api_key": self.lidarr_api_key,
                "root_folder_path": self.root_folder_path,
                "quality_profile_id": self.quality_profile_id,
                "metadata_profile_id": self.metadata_profile_id,
            }
            socketio.emit("settingsLoaded", data)
        except Exception as e:
            self.lidify_logger.error(f"Failed to load settings: {str(e)}")

    def update_settings(self, data):
        try:
            self.lidarr_address = data["lidarr_address"]
            self.lidarr_api_key = data["lidarr_api_key"]
            self.root_folder_path = data["root_folder_path"]
            self.quality_profile_id = data["quality_profile_id"]
            self.metadata_profile_id = data["metadata_profile_id"]
        except Exception as e:
            self.lidify_logger.error(f"Failed to update settings: {str(e)}")

    def format_numbers(self, count):
        if count >= 1000000:
            return f"{count / 1000000:.1f}M"
        elif count >= 1000:
            return f"{count / 1000:.1f}K"
        else:
            return count

    def save_config_to_file(self):
        try:
            with open(self.settings_config_file, "w") as json_file:
                json.dump(
                    {
                        "lidarr_address": self.lidarr_address,
                        "lidarr_api_key": self.lidarr_api_key,
                        "root_folder_path": self.root_folder_path,
                        "fallback_to_top_result": self.fallback_to_top_result,
                        "lidarr_api_timeout": float(self.lidarr_api_timeout),
                        "quality_profile_id": self.quality_profile_id,
                        "metadata_profile_id": self.metadata_profile_id,
                        "search_for_missing_albums": self.search_for_missing_albums,
                        "dry_run_adding_to_lidarr": self.dry_run_adding_to_lidarr,
                        "app_name": self.app_name,
                        "app_rev": self.app_rev,
                        "app_url": self.app_url,
                        "last_fm_api_key": self.last_fm_api_key,
                        "last_fm_api_secret": self.last_fm_api_secret,
                        "mode": self.mode,
                        "auto_start": self.auto_start,
                        "auto_start_delay": self.auto_start_delay,
                    },
                    json_file,
                    indent=4,
                )

        except Exception as e:
            self.lidify_logger.error(f"Error Saving Config: {str(e)}")

app = Flask(__name__)
app.secret_key = "secret_key"
socketio = SocketIO(app)
data_handler = DataHandler()

@app.route("/")
def home():
    return render_template("base.html")

@socketio.on("side_bar_opened")
def side_bar_opened():
    if data_handler.lidarr_items:
        ret = {"Status": "Success", "Data": data_handler.lidarr_items, "Running": not data_handler.stop_event.is_set()}
        socketio.emit("lidarr_sidebar_update", ret)

@socketio.on("get_lidarr_artists")
def get_lidarr_artists():
    thread = threading.Thread(target=data_handler.get_artists_from_lidarr, name="Lidarr_Thread")
    thread.daemon = True
    thread.start()

@socketio.on("finder")
def find_similar_artists(data):
    thread = threading.Thread(target=data_handler.find_similar_artists, args=(data,), name="Find_Similar_Thread")
    thread.daemon = True
    thread.start()

@socketio.on("adder")
def add_artists(data):
    thread = threading.Thread(target=data_handler.add_artists, args=(data,), name="Add_Artists_Thread")
    thread.daemon = True
    thread.start()

@socketio.on("connect")
def connection():
    data_handler.connection()

@socketio.on("disconnect")
def disconnection():
    data_handler.disconnection()

@socketio.on("load_settings")
def load_settings():
    data_handler.load_settings()

@socketio.on("update_settings")
def update_settings(data):
    data_handler.update_settings(data)
    data_handler.save_config_to_file()

@socketio.on("start_req")
def starter(data):
    data_handler.start(data)

@socketio.on("stop_req")
def stopper():
    data_handler.stop_event.set()

@socketio.on("load_more_artists")
def load_more_artists():
    thread = threading.Thread(target=data_handler.find_similar_artists, name="FindSimilar")
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
