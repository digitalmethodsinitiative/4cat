#!/opt/venv/bin/python3
import argparse
import os
import shlex
import subprocess
from pathlib import Path

cli = argparse.ArgumentParser()
cli.add_argument("--input_dir", "-i", default="", help="File path to input folder with extracted videos and nothing else")
cli.add_argument("--output_dir", "-o", default="results", help="File path to output folder which will be created")
cli.add_argument("--framerate", "-f", default="1.0", help="Frames per second to be extracted")
args = cli.parse_args()

input_directory = Path(args.input_dir)
filenames = os.listdir(input_directory)
output_directory = Path(args.output_dir)
output_directory.mkdir(exist_ok=True)
frame_rate = float(args.framerate)

for video_filename in filenames:
    if video_filename in ['ffmpeg_wrapper.py', 'results', '.metadata.json']:
        continue
    path = Path(input_directory).joinpath(video_filename)
    vid_name = path.stem
    video_dir = Path(output_directory).joinpath(vid_name)
    video_dir.mkdir(exist_ok=True)

    command = f"ffmpeg -i {path} -s 144x144 -r {frame_rate} {video_dir}/video_frame_%07d.jpeg"

    result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        ffmpeg_output = result.stdout.decode("utf-8")
        ffmpeg_error = result.stderr.decode("utf-8")
    except UnicodeDecodeError as e:
        error = 'Error decoding results for video %s: %s' % (str(path), str(e))
        print(error)

    if ffmpeg_output:
        with open(video_dir.joinpath('ffmpeg_output.log'), 'w') as outfile:
            outfile.write(ffmpeg_output)

    if ffmpeg_error:
        with open(video_dir.joinpath('ffmpeg_error.log'), 'w') as outfile:
            outfile.write(ffmpeg_error)

