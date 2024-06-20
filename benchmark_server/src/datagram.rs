use std::{
    io,
    net::{ToSocketAddrs, UdpSocket},
    ops::{Deref, DerefMut},
    time::Duration,
};

#[cfg(unix)]
use std::{os::unix::net::UnixDatagram, path::Path};

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
}

impl DatagramClient {
    pub fn udp<A: ToSocketAddrs>(addr: A) -> io::Result<Self> {
        let socket = UdpSocket::bind("127.0.0.1:0")?;

        socket.connect(addr)?;

        Ok(Self { inner: Box::new(socket) })
    }

    #[cfg(unix)]
    pub fn unix<P: AsRef<Path>>(path: P) -> io::Result<Self> {
        let socket = UnixDatagram::unbound()?;

        socket.connect(path)?;

        Ok(Self { inner: Box::new(socket) })
    }

    pub fn recv_owned(&mut self, bufsize: usize) -> io::Result<Vec<u8>> {
        let mut buffer: Vec<u8> = vec![0; bufsize];
        if !buffer.is_empty() {
            let bufsize = self.recv(&mut buffer)?;
            buffer = buffer[..bufsize].to_owned();
        }
        Ok(buffer)
    }
}

impl Deref for DatagramClient {
    type Target = dyn ConnectedDatagramEndpoint;

    fn deref(&self) -> &Self::Target {
        self.inner.as_ref()
    }
}

impl DerefMut for DatagramClient {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.inner.as_mut()
    }
}
