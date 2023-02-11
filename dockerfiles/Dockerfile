FROM nvcr.io/nvidia/tensorrt:23.01-py3

RUN apt update -y && apt install -y libgl1
# install additional python packages
COPY ./requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
