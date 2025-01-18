use std::{
    io,
    net::{ToSocketAddrs, UdpSocket},
    ops::{Deref, DerefMut},
    path::Path,
    time::Duration,
};

#[cfg(unix)]
use std::os::unix::net::UnixDatagram;

pub trait ConnectedDatagramEndpoint {
    fn send(&self, buf: &[u8]) -> io::Result<usize>;
    fn recv(&self, buf: &mut [u8]) -> io::Result<usize>;
    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()>;
}

impl ConnectedDatagramEndpoint for UdpSocket {
    fn send(&self, buf: &[u8]) -> io::Result<usize> {
        self.send(buf)
    }

    fn recv(&self, buf: &mut [u8]) -> io::Result<usize> {
        self.recv(buf)
    }

    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)?;
        self.set_write_timeout(timeout)?;
        Ok(())
    }
}

#[cfg(unix)]
impl ConnectedDatagramEndpoint for UnixDatagram {
    fn send(&self, buf: &[u8]) -> io::Result<usize> {
        self.send(buf)
    }

    fn recv(&self, buf: &mut [u8]) -> io::Result<usize> {
        self.recv(buf)
    }

    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        self.set_read_timeout(timeout)?;
        self.set_write_timeout(timeout)?;
        Ok(())
    }
}

impl<S: ConnectedDatagramEndpoint + ?Sized> ConnectedDatagramEndpoint for Box<S> {
    fn send(&self, buf: &[u8]) -> io::Result<usize> {
        (**self).send(buf)
    }

    fn recv(&self, buf: &mut [u8]) -> io::Result<usize> {
        (**self).recv(buf)
    }

    fn set_timeout(&self, timeout: Option<Duration>) -> io::Result<()> {
        (**self).set_timeout(timeout)
    }
}

pub struct DatagramClient {
    inner: Box<dyn ConnectedDatagramEndpoint + Send>,
    cleanup: Option<Box<dyn FnOnce() + Send>>,
}

impl DatagramClient {
    pub fn udp(addr: impl ToSocketAddrs) -> io::Result<Self> {
        let socket = UdpSocket::bind("127.0.0.1:0")?;

        socket.connect(addr)?;

        Ok(Self {
            inner: Box::new(socket),
            cleanup: None,
        })
    }

    pub fn unix(path: impl AsRef<Path>, local_path: impl AsRef<Path>) -> io::Result<Self> {
        #[cfg(unix)]
        {
            let local_path = local_path.as_ref().to_path_buf();
            let socket = UnixDatagram::bind(&local_path)?;

            socket.connect(path).inspect_err(|_| {
                std::fs::remove_file(&local_path).ok();
            })?;

            Ok(Self {
                inner: Box::new(socket),
                cleanup: Some(Box::new(move || {
                    std::fs::remove_file(local_path).ok();
                })),
            })
        }

        #[cfg(not(unix))]
        {
            drop(path);
            drop(local_path);
            Err(io::Error::other("UNIX datagram not supported"))
        }
    }

    pub fn recv_owned(&mut self, max_size: usize) -> io::Result<Box<[u8]>> {
        let mut buffer: Vec<u8> = vec![0; max_size];
        let bufsize = self.recv(&mut buffer)?;
        buffer.truncate(bufsize);
        Ok(buffer.into_boxed_slice())
    }
}

impl Deref for DatagramClient {
    type Target = dyn ConnectedDatagramEndpoint;

    fn deref(&self) -> &Self::Target {
        &*self.inner
    }
}

impl DerefMut for DatagramClient {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut *self.inner
    }
}

impl Drop for DatagramClient {
    fn drop(&mut self) {
        if let Some(cleanup) = self.cleanup.take() {
            (cleanup)();
        }
    }
}
