#!/usr/bin/env python3

import sys
from pathlib import Path

# Ensure that virutal environment is activated.
bin_dir = Path(sys.prefix)
if bin_dir.name == 'usr':
    script_dir = Path(__file__).parent
    env_full_path = script_dir.resolve() / 'env'
    if env_full_path.is_dir():
        activate_path = env_full_path / 'bin' / 'activate'
    else:
        print(f"ERROR: Virtual environment not found at \"{env_full_path}\"")
        exit(1)
    # Virtual environment not activated.
    print("ERROR: Need to activate virtual environment:")
    print(f"$ . {activate_path}")
    exit(1)

import argparse
import ffmpeg
# ffmpeg API: https://kkroening.github.io/ffmpeg-python
# ffmpeg Ex: https://github.com/kkroening/ffmpeg-python

def validate_file(input_file_string):
    # Get full path to input file.
    #   .expanduser() expands out possible "~"
    #   .resolve() expands relative paths and symlinks
    input_file = Path(input_file_string).expanduser().resolve()
    if not input_file.is_file():
        print(f"Error: invalid input file: {file_path}")
        return None
    return input_file

def parse_timestamp(timestamp):
    """
    Return timestamp string HH:MM:SS as a float of total seconds.
    """
    parts = timestamp.split(':')
    seconds = 0.0
    for i in range(len(parts)):
        # Convert empty placeholder to zero.
        if parts[-(i+1)] == '':
            parts[-(i+1)] = 0
        seconds += float(parts[-(i+1)])*60**i if len(parts) > i else 0
    return seconds

def get_properties(infile):
    if infile == '<infile>':
        # Dummy file for printing command.
        return 'placeholder'
    try:
        probe = ffmpeg.probe(infile)
    except ffmpeg._run.Error:
        print("Error: Not an audio or video file?")
        exit(1)
    return probe['streams']

def show_properties(infile):
    streams = get_properties(infile)
    print()
    for stream in streams:
        for k, v in stream.items():
            skip = ['disposition', 'tags']
            if k in skip:
                continue
            print(f"{k:<24} {v}")
        print()

def split_into_streams(infile):
    # Get input file details.
    file_info = get_properties(infile)
    if file_info == 'placeholder':
        audio_streams = ['placeholder']
        video_streams = ['placeholder']
    else:
        audio_streams = [a for a in file_info if a['codec_type'] == 'audio']
        video_streams = [v for v in file_info if v['codec_type'] == 'video']

    # Split into streams.
    stream = ffmpeg.input(str(infile))
    video = stream.video #stream['v']
    audio = stream.audio #stream['a']
    return audio_streams, video_streams, audio, video

def change_playback_speed(input_file_string, factor, rates):
    # Validate input_file.
    input_file = validate_file(input_file_string)
    if not input_file:
        return

    output_file = input_file.with_name(f"{input_file.stem}.{str(factor)}.mp4")
    stream = build_speed_stream(input_file, output_file, factor, rates)
    ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)

def convert_file(input_file_string, rates, output_format='mp4'):
    # Validate input_file.
    input_file = validate_file(input_file_string)
    if not input_file:
        return

    audio_bitrate = rates[0]
    video_bitrate = rates[1]
    framerate = rates[2]

    if output_format == 'mp4':
        # Create output_file name by adding specs to input_file name.
        #   Output to same directory as input_file.
        specs_str = f"v{round(video_bitrate/1000)}kbps_{framerate}fps_a{round(audio_bitrate/1000)}kbps"
        output_file = input_file.with_name(f"{input_file.stem}_{specs_str}.mp4")
        stream = build_video_stream(input_file, output_file, rates)
    elif output_format == 'mp3':
        # Output to same directory as input_file.
        specs_str = f"a{round(audio_bitrate/1000)}kbps"
        output_file = input_file.with_name(f"{input_file.stem}_{specs_str}.mp3")
        stream = build_audio_stream(input_file, output_file, rates)
    ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)

def trim_file(input_file_string, endpoints, rates):
    # Validate input file.
    input_file = validate_file(input_file_string)
    if not input_file:
        return

    # Convert timestamp(s) to seconds.
    endpoints = [parse_timestamp(e) for e in endpoints]
    duration = endpoints[1] -  endpoints[0]

    # Create output_file name by adding "k" to input_file name.
    #   Output to same directory as input_file.
    output_file = input_file.with_name(f"{input_file.stem}_{duration}s.mp4")
    stream = build_trim_stream(input_file, output_file, endpoints, rates)
    ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)

def generate_output_stream(vstreams, astreams, video, audio, rates, outfile):
    # Define output constants.
    bufsize = 100000
    audio_bitrate = rates[0]
    video_bitrate = rates[1]
    format = 'mp4'

    if vstreams and astreams:
        stream = ffmpeg.output(
            video, audio,
            str(outfile),
            # Set output video bitrate to 500kbps for projection.
            video_bitrate=video_bitrate,
            maxrate=video_bitrate,
            bufsize=bufsize,
            # Set output audio bitrate to 128kbps for projection.
            audio_bitrate=audio_bitrate,
            format=format,
        )
    elif vstreams and not astreams:
        stream = ffmpeg.output(
            video,
            str(outfile),
            # Set output video bitrate to 500kbps for projection.
            video_bitrate=video_bitrate,
            maxrate=video_bitrate,
            bufsize=bufsize,
            format=format,
        )
    elif astreams and not vstreams: # audio-only stream
        format = 'mp3'
        stream = ffmpeg.output(
            audio,
            str(outfile),
            # Set output audio bitrate to 128kbps for projection.
            audio_bitrate=audio_bitrate,
            format=format,
        )
    return stream

def build_audio_stream(infile, outfile, rates):
    # Get stream details.
    audio_streams, video_streams, audio, video = split_into_streams(infile)

    # Remove video streams.
    video_streams = None

    # Output correct stream.
    stream = generate_output_stream(video_streams, audio_streams, video, audio, rates, outfile)
    return stream

def build_video_stream(infile, outfile, rates):
    # Get stream details.
    audio_streams, video_streams, audio, video = split_into_streams(infile)

    # Determine frame rate of input video.
    fps = rates[2] # default value
    if video_streams and type(video_streams[0]) != str:
        # Determine maxiumum frame rate from first video stream in input file.
        avg_fps_str = video_streams[0]['avg_frame_rate'] # picks 1st video stream in list
        avg_fps = round(int(avg_fps_str.split('/')[0]) / int(avg_fps_str.split('/')[1]))
        fps = min([avg_fps, fps])

    # Define video max height to 720p (nominal HD).
    video = ffmpeg.filter(video, 'scale', -1, 'min(720, ih)')
    # Define max framerate.
    video = ffmpeg.filter(video, 'fps', fps)

    # Output correct stream.
    stream = generate_output_stream(video_streams, audio_streams, video, audio, rates, outfile)
    return stream

def build_speed_stream(infile, outfile, factor, rates):
    # Get stream details.
    audio_streams, video_streams, audio, video = split_into_streams(infile)

    # Set playback timestamps.
    video = ffmpeg.filter(video, 'setpts', f"{str(1 / factor)}*PTS")
    # Adjust audio speed.
    audio = ffmpeg.filter(audio, 'atempo', f"{str(factor)}")

    # Output correct stream.
    stream = generate_output_stream(video_streams, audio_streams, video, audio, rates, outfile)
    return stream

def build_trim_stream(infile, outfile, endpoints, rates):
    # Get input file details.
    file_info = get_properties(infile)
    if file_info == 'placeholder':
        audio_streams = ['placeholder']
        video_streams = ['placeholder']
    else:
        audio_streams = [a for a in file_info if a['codec_type'] == 'audio']
        video_streams = [v for v in file_info if v['codec_type'] == 'video']

    # Get stream details.
    stream = ffmpeg.input(str(infile), **{'ss': endpoints[0]}, **{'to': endpoints[1]})

    # Output correct stream.
    stream = ffmpeg.output(stream, str(outfile))
    return stream

def show_command(args):
    if args.speed:
        stream = build_speed_stream('<infile>', '<outfile>.mp4', args.speed)
    else:
        stream = build_video_stream('<infile>', '<outfile.mp4>', args.rates)
    print(f"NOTE: If you run the ffmpeg command directly, the argument after -filter_complex needs to be quoted.\n")
    print(f"ffmpeg {' '.join(ffmpeg.get_args(stream))}\n")

def main():
    # Build arguments and options list.
    description = "Convert video file to MP4, ensuring baseline video quality:\n\
  * Default:  720p, 500 Kbps, 25 fps for projected video\n\
  * Tutorial: 720p, 200 Kbps, 10 fps for tutorial video"
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    parser.add_argument(
        '-a', '--audio',
        action='store_true',
        help="Convert file(s) to MP3 audio."
    )
    parser.add_argument(
        '-c', '--command',
        action='store_true',
        help="Print the equivalent ffmpeg bash command."
    )
    parser.add_argument(
        '-i', '--info',
        action='store_true',
        help="Show audio and video properties of given file (only 1 accepted)."
    )
    parser.add_argument(
        '-s', '--speed',
        type=float,
        help="Change the playback speed of the video using the given factor (0 to 1).",
    )
    parser.add_argument(
        '-t', '--tutorial',
        dest='rates',
        action='store_const',
        const=(128000, 200000, 10),
        default=(128000, 500000, 25),
        help="Use lower bitrate and fewer fps for short tutorial videos."
    )
    parser.add_argument(
        '-k', '--trim',
        nargs=2,
        type=str,
        help="Trim the file to content between given timestamps (HH:MM:SS)."
    )
    parser.add_argument(
        "video",
        nargs='*',
        help="Space-separated list of video files to normalize."
    )

    args = parser.parse_args()
    if args.command:
        # Show the ffmpeg bash command.
        show_command(args)

    for input_file in args.video:
        if args.info:
            # Show the video file info.
            show_properties(input_file)
        elif args.speed:
            # Attempt to change the playback speed of all passed video files.
            change_playback_speed(input_file, args.speed, args.rates)
        elif args.trim:
            # Trim the file using given timestamps.
            trim_file(input_file, args.trim, args.rates)
        elif args.audio:
            # Convert file(s) to normalized MP3.
            convert_file(input_file, args.rates, output_format='mp3')
        else:
            # Attempt to normalize all passed video files.
            convert_file(input_file, args.rates, output_format='mp4')


if __name__ == '__main__':
    main()
