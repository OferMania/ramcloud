# Install the dependencies required to build RAMCloud and run the RAMCloud tests. This is used as the development
# environment.
FROM debian:bullseye
WORKDIR /src/ramcloud
RUN apt-get update \
 && apt-get install --yes \
      2to3 \
      apt-transport-https \
      build-essential \
      ca-certificates \
      cmake \
      curl \
      g++ \
      gdb \
      git \
      libboost-dev \
      libboost-filesystem-dev \
      libboost-program-options-dev \
      libboost-system-dev \
      libibverbs-dev \
      libpcre++-dev \
      libssl-dev \
      libzookeeper-mt-dev \
      ninja-build \
      pipenv \
      procps \
      protobuf-compiler \
      python3 \
      python3-pip \
      software-properties-common \
      stgit \
      vim \
      # wget is great for troubleshooting zookeeper installations
      wget \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install pipenv

# Install python3 pip packages and logging for talking with ramcloud-test
RUN mkdir --parent /tmp/pip \
 && chmod a+rw /tmp/pip \
 && mkdir --parent /src/testing \
 && chmod a+rw /src/testing
COPY ./config/Pipfile      /tmp/pip/
COPY ./config/Pipfile.lock /tmp/pip/
COPY ./config/log.ini      /src/testing/
RUN cd /tmp/pip \
 && pipenv install --system --deploy

RUN curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add - \
 && add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/debian bullseye stable" \
 && apt-get update \
 && apt-get install --yes \
      docker-ce \
 && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/src/ramcloud/bindings/python:/src/ramcloud/localcluster/src:/src/ramcloud/localcluster/testing
ENV LD_LIBRARY_PATH=/src/ramcloud/install/lib

ENV GTEST_VERSION=1.12.1
RUN cd /usr/include \
 && wget \
     --quiet \
     --output-document=- \
     "https://github.com/google/googletest/archive/release-${GTEST_VERSION}.tar.gz" \
  | tar --extract --gz --directory=. \
 && mkdir "googletest-release-${GTEST_VERSION}/build" \
 && cd "googletest-release-${GTEST_VERSION}/build" \
 && cmake -GNinja -DBUILD_SHARED_LIBS=ON .. \
 && ninja \
 && ninja install

ENV GTEST_DIR="/usr/include/googletest-release-${GTEST_VERSION}/googletest"

ENV MIMALLOC_VERSION=2.0.9
RUN cd /usr/local/src \
 && wget \
     --quiet \
     --output-document=- \
     "https://github.com/microsoft/mimalloc/archive/refs/tags/v${MIMALLOC_VERSION}.tar.gz" \
  | tar --extract --gz --directory=. \
 && mkdir -p "/usr/local/include/mimalloc" \
 && cd "mimalloc-${MIMALLOC_VERSION}/include" \
 && cp -r * "/usr/local/include/mimalloc" \
 && mkdir -p "/usr/local/lib/mimalloc" \
 && cd "/usr/local/lib/mimalloc" \
 && cmake -DMI_SECURE=ON "/usr/local/src/mimalloc-${MIMALLOC_VERSION}" \
 && make

ENV LD_PRELOAD="/usr/local/lib/mimalloc/libmimalloc-secure.so"
