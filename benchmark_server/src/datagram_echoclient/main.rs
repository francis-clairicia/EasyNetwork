use std::{
    io,
    sync::{mpsc::channel, Arc, Barrier},
    time::{Duration, Instant},
};

use benchmark_server::{
    datagram::DatagramClient,
    report::{Report, RequestReport, TestReport},
};
use clap::{Parser, ValueEnum};

#[derive(Debug, Parser, Clone)]
struct Args {
    #[arg(long = "msize", default_value_t = 1024, help = "message size in bytes")]
    message_size: usize,

    #[arg(long, default_value_t = 30, help = "duration of test in seconds")]
    duration: u64,

    #[arg(long, default_value_t = 2, help = "socket timeout in seconds")]
    timeout: u32,

    #[arg(long = "concurrency", default_value_t = 3, help = "number of workers")]
    workers: usize,

    #[arg(long, default_value_t = String::from("127.0.0.1:25000"), help = "address:port of echoserver")]
    addr: String,

    #[arg(long, value_enum, default_value_t, help = "report output format")]
    output_format: OutputFormat,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
enum OutputFormat {
    Text,
    Json,
}

impl Default for OutputFormat {
    fn default() -> Self {
        Self::Text
    }
}

fn client_from_args(args: &Args, worker_id: u64) -> io::Result<DatagramClient> {
    let client = {
        if args.addr.starts_with("file://") {
            let path = std::path::Path::new(args.addr.trim_start_matches("file://"));
            let local_path = path.with_file_name(format!("client-{}-{}.sock", worker_id, uuid::Uuid::new_v4().simple()));
            DatagramClient::unix(path, local_path)?
        } else {
            DatagramClient::udp(&args.addr)?
        }
    };

    client.set_timeout(Some(Duration::from_secs(args.timeout as u64)))?;

    Ok(client)
}

fn start_workers(args: &Args) -> io::Result<std::sync::mpsc::Receiver<RequestReport>> {
    let barrier = Arc::new(Barrier::new(args.workers));
    let (sender, receiver) = channel::<RequestReport>();

    for worker_id in 0..args.workers {
        let barrier = barrier.clone();
        let sender = sender.clone();
        let mut client = client_from_args(args, worker_id as u64)?;

        let request = "x".repeat(args.message_size);
        let duration = Duration::from_secs(args.duration);

        std::thread::spawn(move || {
            client.send(b"ping").unwrap();
            if *client.recv_owned(128).unwrap() != *b"ping" {
                panic!("socket read")
            }

            let mut recv_buffer: Vec<u8> = vec![0; request.len()];

            barrier.wait();

            let mut current_test_duration = Duration::ZERO;

            while current_test_duration < duration {
                let request_start_time = Instant::now();
                client.send(request.as_bytes()).unwrap();
                client.recv(&mut recv_buffer).unwrap();
                let request_duration = request_start_time.elapsed();
                current_test_duration += request_duration;
                sender.send(RequestReport::new(request_duration, worker_id)).unwrap();
            }
        });
    }

    Ok(receiver)
}

fn main() -> io::Result<()> {
    let args = Args::parse();
    const MESSAGES_PER_REQUEST: usize = 1;

    let mut report_builder = TestReport::new(Duration::from_secs(args.duration), MESSAGES_PER_REQUEST, args.message_size);

    start_workers(&args)?
        .into_iter()
        .for_each(|report| report_builder.add(report));

    let report = Report::try_from(report_builder).map_err(io::Error::other)?;

    match args.output_format {
        OutputFormat::Text => print!("{}", report),
        OutputFormat::Json => serde_json::to_writer(io::stdout(), &report)?,
    };

    Ok(())
}
