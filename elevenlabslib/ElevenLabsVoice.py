from __future__ import annotations

import os
import queue

import threading
from typing import Optional, Tuple, Any

import soundfile as sf
import sounddevice as sd

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from elevenlabslib.ElevenLabsSample import ElevenLabsSample
    from elevenlabslib.ElevenLabsUser import ElevenLabsUser

from elevenlabslib.helpers import *
from elevenlabslib.helpers import _api_json,_api_del,_api_get,_api_multipart


# These are hardcoded because they just plain work. If you really want to change them, please be careful.
_playbackBlockSize = 2048
_downloadChunkSize = 4096
class ElevenLabsVoice:
    """
    Represents a voice in the ElevenLabs API.

    It's the parent class for all voices, and used directly for the premade and designed ones.
    """
    @staticmethod
    def edit_stream_settings(playbackBlockSize=None, downloadChunkSize=None) -> None:
        """
        This function lets you override the default values used for the streaming function.

        Danger:
            This change affects all voices.

            Please only do this if you know what you're doing.

        Parameters:
            playbackBlockSize (int): The size (in frames) of the blocks used for playback.
            downloadChunkSize (int): The size (in bytes) of the chunks to be downloaded.
        """
        global _playbackBlockSize, _downloadChunkSize
        if playbackBlockSize is not None:
            _playbackBlockSize = playbackBlockSize
        if downloadChunkSize is not None:
            _downloadChunkSize = downloadChunkSize

    @staticmethod
    def voiceFactory(voiceData, linkedUser: ElevenLabsUser) -> ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice:
        """
        Initializes a new instance of ElevenLabsVoice or one of its subclasses depending on voiceData.

        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the ElevenLabsUser class representing the linked user.

        Returns:
            ElevenLabsVoice | ElevenLabsDesignedVoice | ElevenLabsClonedVoice: The voice object
        """
        if voiceData["category"] == "premade":
            return ElevenLabsVoice(voiceData, linkedUser)
        elif voiceData["category"] == "cloned":
            return ElevenLabsClonedVoice(voiceData, linkedUser)
        elif voiceData["category"] == "generated":
            return ElevenLabsDesignedVoice(voiceData, linkedUser)
        else:
            raise ValueError(voiceData["category"] + " is not a valid voice category!")

    def __init__(self, voiceData, linkedUser:ElevenLabsUser):
        """
        Initializes a new instance of the ElevenLabsVoice class.
        Don't use this constructor directly. Use the factory instead.

        Args:
            voiceData: A dictionary containing the voice data.
            linkedUser: An instance of the ElevenLabsUser class representing the linked user.
        """
        self._linkedUser = linkedUser
        # This is the name at the time the object was created. It won't be updated.
        # (Useful to iterate over all voices to find one with a specific name without spamming the API)
        self.initialName = voiceData["name"]
        self._voiceID = voiceData["voice_id"]
        self._category = voiceData["category"]

    def get_settings(self) -> dict:
        """
        Returns:
            dict: The current generation settings of the voice (stability and clarity).
        """
        response = _api_get("/voices/" + self._voiceID + "/settings", self._linkedUser.headers)
        return response.json()
    def get_info(self) -> dict:
        """
        Tip:
            I've only added specific getters for the most common attributes (name/description).

            Use this function for all other metadata.

        Returns:
            dict: A dict containing all the metadata for the voice, such as the name, the description, etc.
        """
        response = _api_get("/voices/" + self._voiceID, self._linkedUser.headers)
        return response.json()

    def get_name(self) -> str:
        """
        Returns:
            str: The name of the voice.
        """
        return self.get_info()["name"]

    def get_description(self) -> str|None:
        """
        Returns:
            str: The description of the voice.
        """
        return self.get_info()["description"]

    def edit_settings(self, stability:float=None, similarity_boost:float=None):
        """
        Note:
            If either argument is omitted, the current values will be used instead.

        Edit the settings of the current voice.

        Args:
            stability (float, optional): The stability of the voice.
            similarity_boost (float, optional): The similarity boost of the voice.

        Raises:
            ValueError: If the provided stability or similarity_boost value is not between 0 and 1.
        """
        if stability is None or similarity_boost is None:
            oldSettings = self.get_settings()
            if stability is None: stability = oldSettings["stability"]
            if similarity_boost is None: stability = oldSettings["similarity_boost"]

        if not(0 <= stability <= 1 and 0 <= similarity_boost <= 1):
            raise ValueError("Please provide a value between 0 and 1.")
        payload = {"stability": stability, "similarity_boost": similarity_boost}
        _api_json("/voices/" + self._voiceID + "/settings/edit", self._linkedUser.headers, jsonData=payload)

    def _generate_payload(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None, model_id:str="eleven_monolingual_v1") -> dict:
        """
        Generates the payload for the text-to-speech API call.

        Args:
            prompt (str): The prompt to generate speech for.
            stability (Optional[float]): A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
            similarity_boost (Optional[float]): A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.
            model_id (str): The ID of the TTS model to use for the generation. Defaults to monolingual english.
        Returns:
            dict: A dictionary representing the payload for the API call.
        """
        payload = {"text": prompt, "model_id": model_id}
        if stability is not None or similarity_boost is not None:
            currentSettings = self.get_settings()
            if stability is None: stability = currentSettings["stability"]
            if similarity_boost is None: similarity_boost = currentSettings["similarity_boost"]
            if not (0 <= stability <= 1 and 0 <= similarity_boost <= 1):
                raise ValueError("Please provide a value between 0 and 1.")
            payload["voice_settings"] = dict()
            payload["voice_settings"]["stability"] = stability
            payload["voice_settings"]["similarity_boost"] = similarity_boost
        return payload

    def generate_audio_bytes(self, prompt:str, stability:Optional[float]=None, similarity_boost:Optional[float]=None, model_id:str="eleven_monolingual_v1") -> bytes:
        """
        Generates speech for the given prompt and returns the audio data as bytes of an mp3 file.

        Tip:
            If you would like to save the audio to disk or otherwise, you can use helpers.save_audio_bytes().

        Args:
        	prompt: The prompt to generate speech for.
        	stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
        	similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.
        	model_id (str): The ID of the TTS model to use for the generation. Defaults to monolingual english.
        Returns:
        	The bytes of the audio file.

        """
        payload = self._generate_payload(prompt, stability, similarity_boost, model_id)
        response = _api_json("/text-to-speech/" + self._voiceID + "/stream", self._linkedUser.headers, jsonData=payload)


        return response.content

    def generate_and_play_audio(self, prompt:str, playInBackground:bool, portaudioDeviceID:Optional[int] = None,
                                stability:Optional[float]=None, similarity_boost:Optional[float]=None,
                                onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None, model_id:str="eleven_monolingual_v1"):
        """
        Generate audio bytes from the given prompt and play them using sounddevice.

        Tip:
            This function downloads the entire file before playing it back, and even if playInBackground is set, it will halt execution until the file is downloaded.
            If you need faster response times and background downloading and playback, use generate_and_stream_audio.

        Parameters:
        	prompt (str): The text prompt to generate audio from.
        	playInBackground (bool): Whether to play audio in the background or wait for it to finish playing.
        	portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
        	stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
        	similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.
        	onPlaybackStart: Function to call once the playback begins
        	onPlaybackEnd: Function to call once the playback ends
        	model_id (str): The ID of the TTS model to use for the generation. Defaults to monolingual english.

        Returns:
            The audio bytes.
        """
        audioData = self.generate_audio_bytes(prompt, stability, similarity_boost, model_id)
        play_audio_bytes(audioData, playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd)
        return audioData

    def generate_and_stream_audio(self, prompt:str, portaudioDeviceID:Optional[int] = None,
                                  stability:Optional[float]=None, similarity_boost:Optional[float]=None, streamInBackground=False,
                     onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None, model_id:str="eleven_monolingual_v1"):
        """

        Note:
            No longer suffers from the skipping issues it had in the past.

        Generate audio bytes from the given prompt and stream them using sounddevice.

        If streamInBackground is true, it will download the audio data in a separate thread, without pausing the main thread.

        Parameters:
            streamInBackground (bool): Whether or not to play the audio (and let the download complete) in a separate thread.
            prompt (str): The text prompt to generate audio from.
            portaudioDeviceID (int, optional): The ID of the audio device to use for playback. Defaults to the default output device.
            stability: A float between 0 and 1 representing the stability of the generated audio. If None, the current stability setting is used.
            similarity_boost: A float between 0 and 1 representing the similarity boost of the generated audio. If None, the current similarity boost setting is used.
            onPlaybackStart: Function to call once the playback begins
            onPlaybackEnd: Function to call once the playback ends
            model_id (str): The ID of the TTS model to use for the generation. Defaults to monolingual english.

        """
        payload = self._generate_payload(prompt, stability, similarity_boost, model_id)
        path = "/text-to-speech/" + self._voiceID + "/stream"

        streamedResponse = requests.post(api_endpoint + path, headers=self._linkedUser.headers, json=payload, stream=True)

        streamer = _AudioChunkStreamer(portaudioDeviceID, onPlaybackStart, onPlaybackEnd)

        if streamInBackground:
            mainThread = threading.Thread(target=streamer.begin_streaming, args=(streamedResponse,))
            mainThread.start()
        else:
            streamer.begin_streaming(streamedResponse)

        return


    def get_preview_url(self) -> str|None:
        """
        Returns:
            str|None: The preview URL of the voice, or None if it hasn't been generated.
        """
        return self.get_info()["preview_url"]

    def get_preview_bytes(self) -> bytes:
        """
        Returns:
            bytes: The preview audio bytes.

        Raises:
            RuntimeError: If no preview URL is available.
        """
        # This will error out if the preview hasn't been generated
        previewURL = self.get_preview_url()
        if previewURL is None:
            raise RuntimeError("No preview URL available!")
        response = requests.get(previewURL, allow_redirects=True)
        return response.content

    def play_preview(self, playInBackground:bool, portaudioDeviceID:Optional[int] = None,
                                onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None) -> None:
        """
        Plays the preview audio.

        Args:
            playInBackground: A bool indicating whether to play the audio in the background.
            portaudioDeviceID: Optional int indicating the device ID to use for audio playback.
        	onPlaybackStart: Function to call once the playback begins
        	onPlaybackEnd: Function to call once the playback ends

        Returns:
            None
        """

        play_audio_bytes(self.get_preview_bytes(), playInBackground, portaudioDeviceID, onPlaybackStart, onPlaybackEnd)
        return

    @property
    def category(self):
        """
        This property indicates the "type" of the voice, whether it's premade, cloned, designed etc.
        """
        return self._category

    @property
    def linkedUser(self):
        """
        Note:
            This property can also be set.
            This is mostly in case some future update adds shared voices (beyond the currently available premade ones).

        The user currently linked to the voice, whose API key will be used to generate audio.

        Returns:
            ElevenLabsUser: The user linked to the voice.

        """
        return self._linkedUser

    @linkedUser.setter
    def linkedUser(self, newUser: ElevenLabsUser):
        """
        Set the user linked to the voice, whose API key will be used.

        Args:
            newUser (ElevenLabsUser): The new user to link to the voice.

        """
        self._linkedUser = newUser

    @property
    def voiceID(self):
        return self._voiceID


class ElevenLabsDesignedVoice(ElevenLabsVoice):
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def edit_voice(self, newName:str = None, newLabels:dict[str, str] = None, description:str = None):
        """
        Edit the name/labels of the voice.

        Args:
            newName (str): The new name
            newLabels (str): The new labels
            description (str): The new description
        """
        currentInfo = self.get_info()
        payload = {
            "name": currentInfo["name"],
            "labels": currentInfo["labels"],
            "description": currentInfo["description"]
        }
        if newName is not None:
            payload["name"] = newName
        if newLabels is not None:
            if len(newLabels.keys()) > 5:
                raise ValueError("Too many labels! The maximum amount is 5.")
            payload["labels"] = newLabels
        if description is not None:
            payload["description"] = description
        _api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload)
    def delete_voice(self):
        """
        This function deletes the voice, and also sets the voiceID to be empty.
        """
        if self._category == "premade":
            raise RuntimeError("Cannot delete premade voices!")
        response = _api_del("/voices/" + self._voiceID, self._linkedUser.headers)
        self._voiceID = ""


class ElevenLabsClonedVoice(ElevenLabsDesignedVoice):
    def __init__(self, voiceData, linkedUser: ElevenLabsUser):
        super().__init__(voiceData, linkedUser)

    def get_samples(self) -> list[ElevenLabsSample]:
        outputList = list()
        samplesData = self.get_info()["samples"]
        from elevenlabslib.ElevenLabsSample import ElevenLabsSample
        for sampleData in samplesData:
            outputList.append(ElevenLabsSample(sampleData, self))
        return outputList

    def add_samples_by_path(self, samples:list[str]|str):
        """
        This function adds samples to the current voice by their file paths.

        Args:
            samples (list[str]|str): A list with the file paths to the audio files or a str containing a single path.

        Raises:
            ValueError: If no samples are provided.

        """
        if isinstance(samples, str):
            samples = list(samples)

        sampleBytes = {}
        for samplePath in samples:
            if "\\" in samplePath:
                fileName = samplePath[samplePath.rindex("\\")+1:]
            else:
                fileName = samplePath
            sampleBytes[fileName] = open(samplePath, "rb").read()
        self.add_samples_bytes(sampleBytes)

    #Requires a dict of filenames and bytes
    def add_samples_bytes(self, samples:dict[str, bytes]):
        """
        This function adds samples to the current voice by their file names and bytes.

        Args:
            samples (dict[str, bytes]): A dictionary of audio file names and their respective bytes.

        Raises:
            ValueError: If no samples are provided.

        """
        if len(samples.keys()) == 0:
            raise ValueError("Please add at least one sample!")

        payload = {"name":self.get_name()}
        files = list()
        for fileName, fileBytes in samples.items():
            files.append(("files", (fileName, io.BytesIO(fileBytes))))

        _api_multipart("/voices/" + self._voiceID + "/edit", self._linkedUser.headers, data=payload, filesData=files)



#This way lies only madness.
_defaultDType = "float32"
class _AudioChunkStreamer:
    def __init__(self,portaudioDeviceID:int = None,onPlaybackStart:Callable=lambda: None, onPlaybackEnd:Callable=lambda: None):
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None  # Needs to be created later.
        self._bytesLock = threading.Lock()
        self._onPlaybackStart = onPlaybackStart
        self._onPlaybackEnd = onPlaybackEnd
        self._frameSize = 0

        if portaudioDeviceID is None:
            portaudioDeviceID = sd.default.device

        self._deviceID = portaudioDeviceID

        self._events: dict[str, threading.Event] = {
            "playbackFinishedEvent": threading.Event(),
            "headerReadyEvent": threading.Event(),
            "soundFileReadyEvent": threading.Event(),
            "downloadDoneEvent": threading.Event(),
            "blockDataAvailable": threading.Event(),
            "playbackStartFired": threading.Event()
        }

    def begin_streaming(self, streamedResponse:requests.Response):
        # Clean all the buffers and reset all events.
        self._q = queue.Queue()
        self._bytesFile = io.BytesIO()
        self._bytesSoundFile: Optional[sf.SoundFile] = None  # Needs to be created later.
        for eventName, event in self._events.items():
            event.clear()

        downloadThread = threading.Thread(target=self._stream_downloader_function, args=(streamedResponse,))
        downloadThread.start()

        while True:
            logging.debug("Waiting for header event...")
            self._events["headerReadyEvent"].wait()
            logging.debug("Header maybe ready?")
            try:
                with self._bytesLock:
                    self._bytesSoundFile = sf.SoundFile(self._bytesFile)
                    logging.debug("File created (" + str(self._bytesFile.tell()) + " bytes read).")
                    self._frameSize = self._bytesSoundFile.channels * sf._ffi.sizeof(self._bytesSoundFile._check_dtype(_defaultDType))
                    self._events["soundFileReadyEvent"].set()
                    break
            except sf.LibsndfileError:
                self._bytesFile.seek(0)
                dataBytes = self._bytesFile.read()
                self._bytesFile.seek(0)
                logging.debug("Error creating the soundfile with " + str(len(dataBytes)) + " bytes of data. Let's clear the headerReady event.")
                self._events["headerReadyEvent"].clear()
                self._events["soundFileReadyEvent"].set()

        stream = sd.RawOutputStream(
            samplerate=self._bytesSoundFile.samplerate, blocksize=_playbackBlockSize,
            device=self._deviceID, channels=self._bytesSoundFile.channels, dtype=_defaultDType,
            callback=self._stream_playback_callback, finished_callback=self._events["playbackFinishedEvent"].set)
        logging.debug("Starting playback...")
        with stream:
            while True:
                data = self._get_data_from_download_thread()
                if len(data) == _playbackBlockSize*self._frameSize:
                    logging.debug("Putting " + str(len(data)) + " bytes in queue.")
                    self._q.put(data)
                else:
                    logging.debug("Got back less data than expected, check if we're at the end...")
                    with self._bytesLock:
                        # This needs to use bytes rather than frames left, as sometimes the number of frames left is wrong.
                        curPos = self._bytesFile.tell()
                        endPos = self._bytesFile.seek(0, os.SEEK_END)
                        self._bytesFile.seek(curPos)
                        if endPos == curPos and self._events["downloadDoneEvent"].is_set():
                            logging.debug("We're at the end.")
                            if data != b"":
                                logging.debug("Still some data left, writing it...")
                                #logging.debug("Putting " + str(len(data)) +
                                #              " bytes in queue.")
                                self._q.put(data)
                            break
                        else:
                            logging.critical("We're not at the end, yet we recieved less data than expected. THIS SHOULD NOT HAPPEN.")
            logging.debug("While loop done.")
            self._events["playbackFinishedEvent"].wait()  # Wait until playback is finished
            self._onPlaybackEnd()
            logging.debug(stream.active)
        logging.debug("Stream done.")
        return

    def _stream_downloader_function(self, streamedResponse:requests.Response):
        # This is the function running in the download thread.
        streamedResponse.raise_for_status()
        totalLength = 0
        logging.debug("Starting iter...")
        for chunk in streamedResponse.iter_content(chunk_size=_downloadChunkSize):
            if self._events["headerReadyEvent"].is_set():
                logging.debug("HeaderReady is set, waiting for the soundfile...")
                self._events["soundFileReadyEvent"].wait()  # Wait for the soundfile to be created.
                if not self._events["headerReadyEvent"].is_set():
                    logging.debug("headerReady was cleared by the playback thread. Header data still missing, download more.")
                    self._events["soundFileReadyEvent"].clear()

            totalLength += len(chunk)
            if len(chunk) != _downloadChunkSize:
                logging.debug("Writing weirdly sized chunk (" + str(len(chunk)) + ")...")

            # Write the new data then seek back to the initial position.
            with self._bytesLock:
                if not self._events["headerReadyEvent"].is_set():
                    logging.debug("headerReady not set, setting it...")
                    self._bytesFile.seek(0, os.SEEK_END)  # MAKE SURE the head is at the end.
                    self._bytesFile.write(chunk)
                    self._bytesFile.seek(0)  # Move the head back.
                    self._events["headerReadyEvent"].set()  # We've never downloaded a single chunk before. Do that and move the head back, then fire the event.
                else:
                    lastReadPos = self._bytesFile.tell()
                    lastWritePos = self._bytesFile.seek(0, os.SEEK_END)
                    self._bytesFile.write(chunk)
                    endPos = self._bytesFile.tell()
                    self._bytesFile.seek(lastReadPos)
                    logging.debug("Write head move: " + str(endPos - lastWritePos))
                    if endPos - lastReadPos > _playbackBlockSize:  # We've read enough data to fill up a block, alert the other thread.
                        logging.debug("Raise available data event - " + str(endPos - lastReadPos) + " bytes available")
                        self._events["blockDataAvailable"].set()

        logging.debug("Download finished - " + str(totalLength) + ".")
        self._events["downloadDoneEvent"].set()
        self._events["blockDataAvailable"].set()  # Ensure that the other thread knows data is available
        return

    def _stream_playback_callback(self, outdata, frames, timeData, status):
        assert frames == _playbackBlockSize

        while True:
            try:
                readData = self._q.get_nowait()
                if len(readData) == 0 and not self._events["downloadDoneEvent"].is_set():
                    logging.debug("An empty item got into the queue. Skip it.")
                    continue
                break
            except queue.Empty as e:
                if self._events["downloadDoneEvent"].is_set():
                    logging.debug("Download (and playback) finished.")  # We're done.
                    raise sd.CallbackStop
                else:
                    # This should NEVER happen, as the getdownloaddata function handles waiting for new data to come in. ABORT.
                    logging.debug("Missing data but download isn't over. What the fuck?")
                    raise sd.CallbackAbort
        #We've read an item from the queue.

        if not self._events["playbackStartFired"].is_set(): #Ensure the callback only fires once.
            self._events["playbackStartFired"].set()
            logging.debug("Firing onPlaybackStart...")
            self._onPlaybackStart()

        # Last read chunk was smaller than it should've been. It's either EOF or that stupid soundFile bug.
        if 0 < len(readData) < len(outdata):
            logging.debug("Data read smaller than it should've been.")
            logging.debug("Read " + str(len(readData)) + " bytes but expected " + str(len(outdata)) + ", padding...")

            # I still don't really understand why this happens - seems to be related to the soundfile bug.
            # Padding it like this means there ends up being a small portion of silence during the playback.

            outdata[:len(readData)] = readData
            outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        elif len(readData) == 0:
            logging.debug("Callback got no data from the queue. Checking if playback is over...")
            with self._bytesLock:
                oldPos = self._bytesFile.tell()
                endPos = self._bytesFile.seek(0, os.SEEK_END)
                if oldPos == endPos and self._events["downloadDoneEvent"].is_set():
                    logging.debug("EOF reached and download over! Stopping callback...")
                    raise sd.CallbackStop
                else:
                    logging.debug("...Read no data but the download isn't over, what the fuck? Panic. Just send silence.")
                    outdata[len(readData):] = b'\x00' * (len(outdata) - len(readData))
        else:
            outdata[:] = readData
    #THIS FUNCTION ASSUMES YOU'VE GIVEN THE THREAD THE LOCK.
    def _soundFile_read_and_fix(self, dataToRead:int=-1, dtype=_defaultDType):
        readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
        logging.debug(f"Expected {dataToRead*self._frameSize} bytes, got back {len(readData)}")
        if len(readData) < dataToRead * self._frameSize:
            logging.debug("Insufficient data read.")
            curPos = self._bytesFile.tell()
            endPos = self._bytesFile.seek(0, os.SEEK_END)
            if curPos != endPos:
                logging.debug("We're not at the end of the file. Check if we're out of frames.")
                logging.debug("Recreating soundfile...")
                self._bytesFile.seek(0)
                newSF = sf.SoundFile(self._bytesFile, mode="r")
                newSF.seek(self._bytesSoundFile.tell() - int(len(readData) / self._frameSize))
                if newSF.frames > self._bytesSoundFile.frames:
                    logging.debug("Frame counter was outdated.")
                    self._bytesSoundFile = newSF
                    readData = self._bytesSoundFile.buffer_read(dataToRead, dtype=dtype)
                    logging.debug("Now read " + str(len(readData)) +
                          " bytes. I sure hope that number isn't zero.")
        return readData

    def _get_data_from_download_thread(self) -> bytes:
        self._events["blockDataAvailable"].wait()  # Wait until a block of data is available.
        self._bytesLock.acquire()
        try:
            readData = self._soundFile_read_and_fix(_playbackBlockSize)
        except AssertionError as en:
            logging.debug("Mismatch in the number of frames read.")
            logging.debug("This only seems to be an issue when it happens with files that have ID3v2 tags.")
            logging.debug("Ignore it and return empty.")
            readData = b""

        currentPos = self._bytesFile.tell()
        self._bytesFile.seek(0, os.SEEK_END)
        endPos = self._bytesFile.tell()
        #logging.debug("Remaining file length: " + str(endPos - currentPos) + "\n")
        self._bytesFile.seek(currentPos)
        remainingBytes = endPos - currentPos

        if remainingBytes < _playbackBlockSize and not self._events["downloadDoneEvent"].is_set():
            logging.debug("Marking no available blocks...")
            self._events["blockDataAvailable"].clear()  # Download isn't over and we've consumed enough data to where there isn't another block available.

        logging.debug("Read bytes: " + str(len(readData)) + "\n")

        self._bytesLock.release()
        return readData

