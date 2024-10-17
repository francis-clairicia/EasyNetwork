use std::{
    io::{self, Read, Write},
    net::{TcpStream, ToSocketAddrs},
    ops::{Deref, DerefMut},
    path::Path,
    time::Duration,
};

#[cfg(unix)]
use std::os::unix::net::UnixStream;

pub trait Stream: Read + Write {
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()>;
}

impl Stream for TcpStream {
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)?;
        self.set_write_timeout(timeout)?;
        Ok(())
    }
}

#[cfg(unix)]
impl Stream for UnixStream {
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)?;
        self.set_write_timeout(timeout)?;
        Ok(())
    }
}

impl<S: Stream> Stream for native_tls::TlsStream<S> {
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.get_ref().set_timeout(timeout)
    }
}

impl<S: Stream + ?Sized> Stream for Box<S> {
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        (**self).set_timeout(timeout)
    }
}

pub struct StreamClient {
    inner: Box<dyn Stream + Send>,
}

impl StreamClient {
    pub fn tcp(addr: impl ToSocketAddrs) -> io::Result<Self> {
        let socket = TcpStream::connect(addr)?;

        socket.set_nodelay(true)?;

        Ok(Self { inner: Box::new(socket) })
    }

    pub fn unix(path: impl AsRef<Path>) -> io::Result<Self> {
        #[cfg(unix)]
        {
            let socket = UnixStream::connect(path)?;

            Ok(Self { inner: Box::new(socket) })
        }

        #[cfg(not(unix))]
        {
            drop(path);
            Err(io::Error::other("UNIX stream not supported"))
        }
    }

    pub fn start_tls(self) -> io::Result<Self> {
        let tls_stream = native_tls::TlsConnector::builder()
            .danger_accept_invalid_certs(true)
            .danger_accept_invalid_hostnames(true)
            .build()
            .map_err(map_native_tls_error)?
            .connect("localhost", self.inner)
            .map_err(map_native_tls_handshake_error)?;

        Ok(Self {
            inner: Box::new(tls_stream),
        })
    }

    pub fn read_owned(&mut self, max_size: usize) -> io::Result<Box<[u8]>> {
        let mut buffer: Vec<u8> = vec![0; max_size];
        let bufsize = self.read(&mut buffer)?;
        buffer.truncate(bufsize);
        Ok(buffer.into_boxed_slice())
    }
}

impl Deref for StreamClient {
    type Target = dyn Stream;

    fn deref(&self) -> &Self::Target {
        &*self.inner
    }
}

impl DerefMut for StreamClient {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut *self.inner
    }
}

fn map_native_tls_error(e: native_tls::Error) -> io::Error {
    io::Error::other(e.to_string())
}

fn map_native_tls_handshake_error<S>(e: native_tls::HandshakeError<S>) -> io::Error {
    match e {
        native_tls::HandshakeError::WouldBlock(_) => io::Error::new(io::ErrorKind::WouldBlock, "Handshake would block"),
        native_tls::HandshakeError::Failure(e) => map_native_tls_error(e),
    }
}
