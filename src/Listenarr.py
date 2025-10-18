import json
import logging
import os
import threading
from flask import Flask, render_template
from flask_socketio import SocketIO
import requests
import musicbrainzngs

APP_NAME = "Listenarr"
APP_VERSION = "0.1.1"


class DataHandler:
    def __init__(self):
        self.app_name = APP_NAME
        self.app_rev = APP_VERSION
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.lidify_logger = logging.getLogger()
        self.musicbrainzngs_logger = logging.getLogger("musicbrainzngs")
        self.musicbrainzngs_logger.setLevel("WARNING")

        self.lidify_logger.warning(f"{'*' * 50}\n")
        self.lidify_logger.warning(f"{APP_NAME} Version: {APP_VERSION}\n")
        self.lidify_logger.warning(f"{'*' * 50}")

        self.search_in_progress_flag = False
        self.clients_connected_counter = 0
        self.config_folder = "config"
        self.recommended_artists = []
        self.lidarr_items = []
        self.lidarr_mbids = []
        self.stop_event = threading.Event()
        self.stop_event.set()
        if not os.path.exists(self.config_folder):
            os.makedirs(self.config_folder)
        self.load_environ_or_config_settings()
        if self.auto_start:
            try:
                auto_start_thread = threading.Timer(
                    self.auto_start_delay, self.automated_startup
                )
                auto_start_thread.daemon = True
                auto_start_thread.start()

            except Exception as e:
                self.lidify_logger.error(f"Auto Start Error: {type(e)} - {str(e)}")

    def load_environ_or_config_settings(self):
        # Defaults
        default_settings = {
            "lidarr_address": "",
            "lidarr_api_key": "",
            "root_folder_path": "",
            "lidarr_api_timeout": 120,
            "quality_profile_id": -1,
            "metadata_profile_id": -1,
            "search_for_missing_albums": False,
            "dry_run_adding_to_lidarr": False,
            "auto_start": False,
            "auto_start_delay": 60,
        }

        # Set blank values to allow getattr to work when loading from file
        self.lidarr_address = ""
        self.lidarr_api_key = ""
        self.root_folder_path = ""
        self.lidarr_api_timeout = ""
        self.quality_profile_id = ""
        self.metadata_profile_id = ""
        self.search_for_missing_albums = ""
        self.dry_run_adding_to_lidarr = ""
        self.auto_start = ""
        self.auto_start_delay = ""

        # Load variables from the configuration file if it exists
        try:
            self.settings_config_file = os.path.join(
                self.config_folder, "settings_config.json"
            )
            if os.path.exists(self.settings_config_file):
                self.lidify_logger.info("Loading Config via file")
                with open(self.settings_config_file, "r") as json_file:
                    ret = json.load(json_file)
                    for key in ret:
                        if getattr(self, key) == "":
                            setattr(self, key, ret[key])

        except Exception as e:
            self.lidify_logger.error(f"Error Loading Config: {type(e)} - {str(e)}")

        # Load defaults if not set by configuration file.
        for key, value in default_settings.items():
            if getattr(self, key) == "":
                setattr(self, key, value)

        # Ensure integer based settings are converted to integers, then enforce min/max
        self.lidarr_api_timeout = int(self.lidarr_api_timeout)
        self.auto_start_delay = int(self.auto_start_delay)
        if self.lidarr_api_timeout < 10:
            self.lidarr_api_timeout = 10
        elif self.lidarr_api_timeout > 300:
            self.lidarr_api_timeout = 300
        if self.auto_start_delay < 10:
            self.auto_start_delay = 10
        elif self.auto_start_delay > 120:
            self.auto_start_delay = 120

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
            self.lidify_logger.error(f"Startup Error: {type(e)} - {str(e)}")
            self.stop_event.set()
            ret = {
                "Status": "Error",
                "Code": str(e),
                "Data": self.lidarr_items,
                "Running": not self.stop_event.is_set(),
            }
            socketio.emit("lidarr_sidebar_update", ret)

        else:
            self.find_similar_artists()

    def get_artists_from_lidarr(self, checked=False):
        try:
            self.lidify_logger.info("Getting Artists from Lidarr")
            self.lidarr_items = []
            self.lidarr_mbids = []
            endpoint = f"{self.lidarr_address}/api/v1/artist"
            headers = {"X-Api-Key": self.lidarr_api_key}
            response = requests.get(
                endpoint, headers=headers, timeout=self.lidarr_api_timeout
            )

            if response.status_code == 200:
                self.full_lidarr_artist_list = response.json()
                self.lidarr_items = [
                    {
                        "name": artist["artistName"],
                        "mbid": artist["foreignArtistId"],
                        "checked": checked,
                    }
                    for artist in self.full_lidarr_artist_list
                ]
                self.lidarr_mbids = [
                    artist["foreignArtistId"] for artist in self.full_lidarr_artist_list
                ]
                self.lidarr_items.sort(key=lambda x: x["name"].lower())
                status = "Success"
                data = self.lidarr_items
            else:
                status = "Error"
                data = response.text

            ret = {
                "Status": status,
                "Code": response.status_code if status == "Error" else None,
                "Data": data,
                "Running": not self.stop_event.is_set(),
            }

        except Exception as e:
            self.lidify_logger.error(f"Getting Artist Error: {type(e)} - {str(e)}")
            ret = {
                "Status": "Error",
                "Code": 500,
                "Data": str(e),
                "Running": not self.stop_event.is_set(),
            }

        finally:
            socketio.emit("lidarr_sidebar_update", ret)

    def filter_similar_artist_response(self, suggested_artist):
        return suggested_artist["artist_mbid"] not in self.lidarr_mbids

    def find_similar_artists(self):
        if self.stop_event.is_set() or self.search_in_progress_flag:
            return
        else:
            try:
                self.lidify_logger.info(
                    "Searching for new artists via ListenBrainz similar-artists"
                )
                self.search_in_progress_flag = True
                payload = [
                    {
                        "artist_mbids": self.artists_to_use_in_search,
                        "algorithm": "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30",
                    }
                ]
                similar_artists = requests.post(
                    "https://labs.api.listenbrainz.org/similar-artists/json",
                    json=payload,
                ).json()
                if len(similar_artists) == 0:
                    socketio.emit(
                        "new_toast_msg",
                        {
                            "title": "No similar artists",
                            "message": "No similar artists found.",
                        },
                    )
                    raise Exception("No similar artists returned")
                filtered_similar_artists = filter(
                    lambda x: x["artist_mbid"] not in self.lidarr_mbids, similar_artists
                )

                for artist in filtered_similar_artists:
                    if self.stop_event.is_set():
                        break
                    try:
                        payload = {"artist_mbids": [artist["artist_mbid"]]}
                        returned_artist = {
                            "Name": artist["name"],
                            "Mbid": artist["artist_mbid"],
                            "Status": "",
                            "Similar_To": "",
                        }
                        for lidarr_artist in self.lidarr_items:
                            if lidarr_artist["mbid"] == artist["reference_mbid"]:
                                returned_artist["Similar_To"] = (
                                    f"Similar to {lidarr_artist['name']}"
                                )
                                break

                        stage = "ListenBrainz artist popularity lookup"
                        popularity_data = requests.post(
                            "https://api.listenbrainz.org/1/popularity/artist",
                            json=payload,
                        ).json()
                        returned_artist["Popularity"] = (
                            f"{self.format_numbers(popularity_data[0]['total_listen_count'])} listens"
                        )
                        returned_artist["Followers"] = (
                            f"{self.format_numbers(popularity_data[0]['total_user_count'])} users"
                        )

                        stage = "Send to client"
                        self.recommended_artists.append(returned_artist)
                        socketio.emit("more_artists_loaded", [returned_artist])

                    except Exception as e:
                        self.lidify_logger.error(f"{stage} error: {type(e)} - {str(e)}")

            except Exception as e:
                self.lidify_logger.error(
                    f"ListenBrainz similar-artists lookup error: {type(e)} - {str(e)}"
                )

            finally:
                self.stop_event.set()
                self.search_in_progress_flag = False
                socketio.emit("finished_finding")

    def add_artists(self, mbid):
        try:
            musicbrainzngs.set_useragent(
                self.app_name, self.app_rev, "https://github.com/andrewtwelch/listenarr"
            )
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
                "rootFolderPath": self.root_folder_path,
                "foreignArtistId": mbid,
                "monitored": True,
                "addOptions": {
                    "searchForMissingAlbums": self.search_for_missing_albums
                },
            }
            if self.dry_run_adding_to_lidarr:
                response = requests.Response()
                response.status_code = 201
            else:
                response = requests.post(
                    lidarr_url,
                    headers=headers,
                    json=payload,
                    timeout=self.lidarr_api_timeout,
                )

            if response.status_code == 201:
                self.lidify_logger.info(
                    f"Artist '{artist_name}' added successfully to Lidarr."
                )
                status = "Added"
                self.lidarr_items.append(
                    {"name": artist_name, "mbid": mbid, "checked": False}
                )
                self.lidarr_items.sort(key=lambda x: x["name"].lower())
                self.lidarr_mbids.append(mbid)
            else:
                self.lidify_logger.error(
                    f"Failed to add artist '{artist_name}' to Lidarr."
                )
                error_data = json.loads(response.content)
                error_message = (
                    error_data[0].get("errorMessage", "No Error Message Returned")
                    if error_data
                    else "Error Unknown"
                )
                self.lidify_logger.error(error_message)
                if "already been added" in error_message:
                    status = "Already in Lidarr"
                    self.lidify_logger.info(
                        f"Artist '{artist_name}' is already in Lidarr."
                    )
                elif "configured for an existing artist" in error_message:
                    status = "Already in Lidarr"
                    self.lidify_logger.info(
                        f"'{artist_folder}' folder already configured for an existing artist."
                    )
                elif "Invalid Path" in error_message:
                    status = "Invalid Path"
                    self.lidify_logger.info(
                        f"Path: {os.path.join(self.root_folder_path, artist_folder, '')} not valid."
                    )
                else:
                    status = "Failed to Add"

            for item in self.recommended_artists:
                if item["Name"] == artist_name:
                    item["Status"] = status
                    socketio.emit("refresh_artist", item)
                    break

        except Exception as e:
            self.lidify_logger.error(f"Adding Artist Error: {type(e)} - {str(e)}")

    def load_settings(self):
        try:
            headers = {"X-Api-Key": self.lidarr_api_key}
            metadata_profiles = []
            quality_profiles = []
            root_folders = []
            if self.lidarr_address:
                status_request = requests.get(
                    f"{self.lidarr_address}/api/v1/system/status",
                    headers=headers,
                    timeout=10,
                )
                if status_request.status_code == 200:
                    metadata_profiles = requests.get(
                        f"{self.lidarr_address}/api/v1/metadataprofile",
                        headers=headers,
                        timeout=10,
                    ).json()
                    quality_profiles = requests.get(
                        f"{self.lidarr_address}/api/v1/qualityprofile",
                        headers=headers,
                        timeout=10,
                    ).json()
                    root_folders = requests.get(
                        f"{self.lidarr_address}/api/v1/rootfolder",
                        headers=headers,
                        timeout=10,
                    ).json()
            data = {
                "lidarr_address": self.lidarr_address,
                "lidarr_api_key": self.lidarr_api_key,
                "lidarr_api_timeout": self.lidarr_api_timeout,
                "root_folder_path": self.root_folder_path,
                "quality_profile_id": self.quality_profile_id,
                "metadata_profile_id": self.metadata_profile_id,
                "search_for_missing_albums": self.search_for_missing_albums,
                "auto_start": self.auto_start,
                "auto_start_delay": self.auto_start_delay,
                "root_folders": root_folders,
                "quality_profiles": quality_profiles,
                "metadata_profiles": metadata_profiles,
            }
            socketio.emit("settingsLoaded", data)
        except Exception as e:
            self.lidify_logger.error(f"Failed to load settings: {type(e)} - {str(e)}")

    def test_settings(self, data):
        try:
            address = data["lidarr_address"]
            key = data["lidarr_api_key"]
            headers = {"X-Api-Key": key}
            status_request = requests.get(
                f"{address}/api/v1/system/status", headers=headers, timeout=10
            )
            if status_request.status_code != 200:
                response_data = {"success": False}
                socketio.emit("settingsTested", data)
            metadata_profiles = requests.get(
                f"{address}/api/v1/metadataprofile", headers=headers, timeout=10
            ).json()
            quality_profiles = requests.get(
                f"{address}/api/v1/qualityprofile", headers=headers, timeout=10
            ).json()
            root_folders = requests.get(
                f"{address}/api/v1/rootfolder", headers=headers, timeout=10
            ).json()
            response_data = {
                "success": True,
                "root_folders": root_folders,
                "metadata_profiles": metadata_profiles,
                "quality_profiles": quality_profiles,
                "root_folder_path": self.root_folder_path,
                "metadata_profile_id": self.metadata_profile_id,
                "quality_profile_id": self.quality_profile_id,
            }
            socketio.emit("settingsTested", response_data)
        except Exception as e:
            self.lidify_logger.error(
                f"Testing connection to Lidarr failed: {type(e)} - {str(e)}"
            )
            response_data = {"success": False}
            socketio.emit("settingsTested", response_data)

    def update_settings(self, data):
        try:
            self.lidarr_address = data["lidarr_address"]
            self.lidarr_api_key = data["lidarr_api_key"]
            self.lidarr_api_timeout = int(data["lidarr_api_timeout"])
            self.root_folder_path = data["root_folder_path"]
            self.quality_profile_id = data["quality_profile_id"]
            self.metadata_profile_id = data["metadata_profile_id"]
            self.search_for_missing_albums = data["search_for_missing_albums"]
            self.auto_start = data["auto_start"]
            self.auto_start_delay = int(data["auto_start_delay"])
            if self.lidarr_api_timeout < 10:
                self.lidarr_api_timeout = 10
            elif self.lidarr_api_timeout > 300:
                self.lidarr_api_timeout = 300
            if self.auto_start_delay < 10:
                self.auto_start_delay = 10
            elif self.auto_start_delay > 120:
                self.auto_start_delay = 120
        except Exception as e:
            self.lidify_logger.error(f"Failed to update settings: {type(e)} - {str(e)}")

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
                        "lidarr_api_timeout": float(self.lidarr_api_timeout),
                        "quality_profile_id": self.quality_profile_id,
                        "metadata_profile_id": self.metadata_profile_id,
                        "search_for_missing_albums": self.search_for_missing_albums,
                        "dry_run_adding_to_lidarr": self.dry_run_adding_to_lidarr,
                        "auto_start": self.auto_start,
                        "auto_start_delay": self.auto_start_delay,
                    },
                    json_file,
                    indent=4,
                )

        except Exception as e:
            self.lidify_logger.error(f"Error Saving Config: {type(e)} - {str(e)}")


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
        ret = {
            "Status": "Success",
            "Data": data_handler.lidarr_items,
            "Running": not data_handler.stop_event.is_set(),
        }
        socketio.emit("lidarr_sidebar_update", ret)


@socketio.on("get_lidarr_artists")
def get_lidarr_artists():
    thread = threading.Thread(
        target=data_handler.get_artists_from_lidarr, name="Lidarr_Thread"
    )
    thread.daemon = True
    thread.start()


@socketio.on("finder")
def find_similar_artists(data):
    thread = threading.Thread(
        target=data_handler.find_similar_artists,
        args=(data,),
        name="Find_Similar_Thread",
    )
    thread.daemon = True
    thread.start()


@socketio.on("adder")
def add_artists(data):
    thread = threading.Thread(
        target=data_handler.add_artists, args=(data,), name="Add_Artists_Thread"
    )
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


@socketio.on("test_settings")
def test_settings(data):
    data_handler.test_settings(data)


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


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
