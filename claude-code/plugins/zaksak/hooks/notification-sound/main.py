#!/usr/bin/env python3
"""
Notification sound hook for Claude Code.

Plays a sound file from the sounds directory when Claude sends notifications.
Randomly selects from available sound files in .claude/hooks/sounds/.
"""

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import List


def get_sound_files(sounds_dir: Path) -> List[Path]:
    """Get all sound files from the sounds directory.

    Args:
        sounds_dir: Path to the sounds directory

    Returns:
        List of paths to sound files
    """
    supported_extensions = {".mp3", ".wav", ".m4a", ".aiff", ".aac", ".flac", ".ogg"}
    sound_files = []

    if sounds_dir.exists() and sounds_dir.is_dir():
        for file_path in sounds_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                sound_files.append(file_path)

    return sound_files


def play_sound_macos(sound_file: Path) -> bool:
    """Play a sound file on macOS using afplay.

    Args:
        sound_file: Path to the sound file to play

    Returns:
        True if playback succeeded, False otherwise
    """
    try:
        # Use afplay command on macOS to play sound
        subprocess.run(
            ["afplay", str(sound_file)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,  # Prevent hanging on long files
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error playing sound with afplay: {e}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("Sound playback timed out", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("afplay command not found (not on macOS?)", file=sys.stderr)
        return False


def play_sound_linux(sound_file: Path) -> bool:
    """Play a sound file on Linux using available tools.

    Args:
        sound_file: Path to the sound file to play

    Returns:
        True if playback succeeded, False otherwise
    """
    # Try different Linux audio players in order of preference
    players = [
        ["paplay", str(sound_file)],  # PulseAudio
        ["aplay", str(sound_file)],  # ALSA
        ["mpg123", "-q", str(sound_file)],  # MPG123 for MP3
        ["ffplay", "-nodisp", "-autoexit", str(sound_file)],  # FFmpeg
    ]

    for player_cmd in players:
        try:
            subprocess.run(
                player_cmd, check=True, capture_output=True, text=True, timeout=10
            )
            return True
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ):
            continue

    print("No suitable audio player found on Linux", file=sys.stderr)
    return False


def play_sound(sound_file: Path) -> bool:
    """Play a sound file using the appropriate method for the OS.

    Args:
        sound_file: Path to the sound file to play

    Returns:
        True if playback succeeded, False otherwise
    """
    platform = sys.platform

    if platform == "darwin":
        return play_sound_macos(sound_file)
    elif platform.startswith("linux"):
        return play_sound_linux(sound_file)
    else:
        print(f"Unsupported platform: {platform}", file=sys.stderr)
        return False


def get_notification_type(message: str) -> str:
    """Determine the type of notification from the message.

    Args:
        message: The notification message

    Returns:
        Type of notification (permission, idle, or general)
    """
    message_lower = message.lower()

    if "permission" in message_lower:
        return "permission"
    elif "waiting" in message_lower or "idle" in message_lower:
        return "idle"
    else:
        return "general"


def main():
    """Main function to handle the notification hook."""
    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract notification message
    message = input_data.get("message", "")

    # Use the global sounds directory at ~/.claude/hooks/sounds
    home_dir = Path.home()
    sounds_dir = home_dir / ".claude" / "hooks" / "sounds"

    # Get available sound files
    sound_files = get_sound_files(sounds_dir)

    if not sound_files:
        print(f"No sound files found in {sounds_dir}", file=sys.stderr)
        sys.exit(0)  # Exit successfully but without playing sound

    # Select a random sound file
    # You could also implement logic to select different sounds based on notification type
    notification_type = get_notification_type(message)
    selected_sound = random.choice(sound_files)

    # Log what we're doing (visible in transcript mode)
    print(
        f"Playing notification sound: {selected_sound.name} for {notification_type} notification"
    )

    # Play the sound
    success = play_sound(selected_sound)

    if not success:
        print(f"Failed to play sound: {selected_sound.name}", file=sys.stderr)
        # Don't fail the hook just because sound didn't play
        sys.exit(0)

    # Exit successfully
    sys.exit(0)


if __name__ == "__main__":
    main()
