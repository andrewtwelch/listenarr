
## Listenarr

Music discovery tool that provides recommendations through the ListenBrainz Labs similar-artists API, based on artists in Lidarr and feeding these recommendations back into Lidarr.
Forked from [Lidify](https://github.com/TheWicklowWolf/Lidify).

### Setup

Listenarr can be run natively or through a container.
To run natively, install dependencies and run `src/Listenarr.py`.
To run as a container, use the image `ghcr.io/andrewtwelch/listenarr:latest` or use the `docker-compose.yml` file. The `main` tag is also available, following the `main` branch.

### Configuration

Once you have started Listenarr, click the settings cog in the top right corner.
Enter your Lidarr address and API key, then click Test to confirm connectivity and load options for Root Folder, Quality Profile and Metadata Profile.
Tick Search for Missing Albums if you want Lidarr to automatically search for releases when an artist is added.
Tick Auto Start and set a delay if you want Listenarr to automatically start a search with all artists when opened.
Light/Dark Mode can be toggled in the bottom right corner.
Click Save to save all settings.

### Usage

Click the sidebar button in the top left to open the sidebar.
Click the Get Lidarr Artists button to pull artists from your Lidarr instance.
Select any number of artists, then click Start to have Listenarr give you a list of recommended artists to add.
Once recommended artists show up, you can click Add to Lidarr to add an artist, or View on ListenBrainz to see more info about the artist.




