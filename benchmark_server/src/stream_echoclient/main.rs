use std::{
    io,
    sync::{mpsc::channel, Arc, Barrier},
    time::{Duration, Instant},
};

use benchmark_server::{
    report::{Report, RequestReport, TestReport},
    stream::StreamClient,
};
use clap::{Parser, ValueEnum};

#[derive(Debug, Parser, Clone)]
struct Args {
    #[arg(long = "msize", default_value_t = 1024, help = "message size in bytes")]
    message_size: usize,

    #[arg(long = "mpr", default_value_t = 1, help = "messages per request")]
    messages_per_request: usize,

    #[arg(long, default_value_t = 30, help = "duration of test in seconds")]
    duration: u64,

    #[arg(long, default_value_t = 2, help = "socket timeout in seconds")]
    timeout: u32,

    #[arg(long = "concurrency", default_value_t = 3, help = "number of workers")]
    workers: usize,

    #[arg(long, default_value_t = String::from("127.0.0.1:25000"), help = "address:port of echoserver")]
    addr: String,

    #[arg(long, help = "enable SSL/TLS connection")]
    ssl: bool,

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

fn client_from_args(args: &Args) -> io::Result<StreamClient> {
    let mut client = {
        if args.addr.starts_with("file://") {
            StreamClient::unix(args.addr.trim_start_matches("file://"))?
        } else {
            StreamClient::tcp(&args.addr)?
        }
    };

    client.set_timeout(Some(Duration::from_secs(args.timeout as u64)))?;

    if args.ssl {
        client = client.start_tls()?;
    }

    Ok(client)
}

fn start_workers(args: &Args) -> io::Result<std::sync::mpsc::Receiver<RequestReport>> {
    let barrier = Arc::new(Barrier::new(args.workers));
    let (sender, receiver) = channel::<RequestReport>();

    if args.messages_per_request == 0 {
        return Err(io::Error::other("--mpr is null"));
    }

    for worker_id in 0..args.workers {
        let barrier = barrier.clone();
        let sender = sender.clone();
        let mut client = client_from_args(args)?;

        let request = format!("{}\n", "x".repeat(args.message_size - 1)).repeat(args.messages_per_request);
        let duration = Duration::from_secs(args.duration);

        std::thread::spawn(move || {
            client.write_all(b"ping\n").unwrap();
            if *client.read_owned(128).unwrap() != *b"ping\n" {
                panic!("socket read")
            }

            let mut recv_buffer: Vec<u8> = vec![0; request.len()];

            barrier.wait();

            let mut current_test_duration = Duration::ZERO;

            while current_test_duration < duration {
                let request_start_time = Instant::now();
                client.write_all(request.as_bytes()).unwrap();
                client.read_exact(&mut recv_buffer).unwrap();
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

    let mut report_builder = TestReport::new(Duration::from_secs(args.duration), args.messages_per_request, args.message_size);

    start_workers(&args)?
        .into_iter()
        .for_each(|report| report_builder.add(report));

    let report = Report::try_from(report_builder).map_err(io::Error::other)?.with_transfer();

    match args.output_format {
        OutputFormat::Text => print!("{}", report),
        OutputFormat::Json => serde_json::to_writer(io::stdout(), &report)?,
    };

    Ok(())
}
