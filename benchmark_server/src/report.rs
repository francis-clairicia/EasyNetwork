use std::{collections::LinkedList, fmt, time::Duration};

use serde::Serialize;

use statrs::statistics::{Data, Distribution, Max, Median, Min, OrderStatistics};

#[derive(Debug, Clone)]
pub struct RequestReport {
    duration: Duration,
}

impl RequestReport {
    pub fn new(duration: Duration) -> Self {
        Self { duration }
    }

    #[inline]
    pub fn duration(&self) -> Duration {
        self.duration
    }
}

#[derive(Debug, Clone)]
pub struct TestReport {
    times_per_request: LinkedList<RequestReport>,
    duration: Duration,
    messages_per_request: usize,
    message_size: usize,
}

impl TestReport {
    pub fn new(duration: Duration, messages_per_request: usize, message_size: usize) -> Self {
        Self {
            times_per_request: Default::default(),
            duration,
            messages_per_request,
            message_size,
        }
    }

    #[inline]
    pub fn add(&mut self, report: RequestReport) {
        self.times_per_request.push_back(report);
    }

    #[inline]
    pub fn duration(&self) -> Duration {
        self.duration
    }

    #[inline]
    pub fn message_size(&self) -> usize {
        self.message_size
    }

    #[inline]
    pub fn number_of_messages(&self) -> usize {
        self.times_per_request.len() * self.messages_per_request
    }

    #[inline]
    pub fn latency_stats(&self) -> Vec<f64> {
        self.times_per_request
            .iter()
            .map(|r| r.duration().as_secs_f64() * 1_000.0)
            .collect()
    }
}

#[derive(Debug, Serialize)]
pub struct Report {
    #[serde(skip)]
    pub message_size: usize,
    #[serde(skip)]
    pub duration: u64,

    pub messages: usize,
    pub latency_min: f64,
    pub latency_max: f64,
    pub latency_mean: f64,
    pub latency_stdev: f64,
    pub latency_q1: f64,
    pub latency_median: f64,
    pub latency_q3: f64,
    pub latency_nb_low_outliers: usize,
    pub latency_nb_high_outliers: usize,
    pub latency_percent_low_outliers: f64,
    pub latency_percent_high_outliers: f64,
    pub rps: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub transfer: Option<f64>,
}

impl Report {
    pub fn with_transfer(mut self) -> Self {
        self.transfer = Some((self.messages as f64 * self.message_size as f64 / (1024.0 * 1024.0)) / self.duration as f64);
        self
    }
}

impl TryFrom<TestReport> for Report {
    type Error = String;

    fn try_from(report: TestReport) -> Result<Self, Self::Error> {
        let duration = report.duration();
        let nb_messages = report.number_of_messages();
        let message_size = report.message_size();
        let mut latency_stats = Data::new(report.latency_stats());
        if duration == Duration::ZERO || latency_stats.is_empty() {
            return Err("No Data".to_owned());
        }

        let rps = nb_messages / duration.as_secs() as usize;

        let latency_min = latency_stats.min();
        let latency_max = latency_stats.max();

        let latency_first_quartile = latency_stats.lower_quartile();
        let latency_median = latency_stats.median();
        let latency_third_quartile = latency_stats.upper_quartile();

        let latency_mean = latency_stats.mean().expect("mean should be available");
        let latency_stdev = latency_stats.std_dev().expect("std dev should be available");

        let latency_iqr = latency_third_quartile - latency_first_quartile;
        let latency_lowerfence = latency_first_quartile - 1.5 * latency_iqr;
        let latency_upperfence = latency_third_quartile + 1.5 * latency_iqr;

        let latency_nb_low_outliers = latency_stats.iter().filter(|&&v| v < latency_lowerfence).count();
        let latency_nb_high_outliers = latency_stats.iter().filter(|&&v| v > latency_upperfence).count();
        let latency_percent_low_outliers = 100.0 * latency_nb_low_outliers as f64 / latency_stats.len() as f64;
        let latency_percent_high_outliers = 100.0 * latency_nb_high_outliers as f64 / latency_stats.len() as f64;

        Ok(Self {
            messages: nb_messages,
            message_size,
            duration: duration.as_secs(),
            latency_min,
            latency_max,
            latency_mean,
            latency_stdev,
            latency_q1: latency_first_quartile,
            latency_median,
            latency_q3: latency_third_quartile,
            latency_nb_low_outliers,
            latency_nb_high_outliers,
            latency_percent_low_outliers,
            latency_percent_high_outliers,
            rps,
            transfer: None,
        })
    }
}

impl fmt::Display for Report {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.messages == 0 {
            return Ok(());
        }

        writeln!(f, "Report")?;
        writeln!(
            f,
            "{messages} (of {message_size:.2} KiB size) in {duration} seconds",
            messages = self.messages,
            message_size = (self.message_size as f64) / 1024.0,
            duration = self.duration,
        )?;
        writeln!(f, "Latency")?;
        writeln!(f, "- min {:.3}ms", self.latency_min)?;
        writeln!(f, "- max {:.3}ms", self.latency_max)?;
        writeln!(f, "- mean {:.3}ms", self.latency_mean)?;
        writeln!(f, "- std {:.3}ms ({:.2}%)", self.latency_stdev, 100.0 * self.latency_stdev / self.latency_mean)?;
        let latency_distribution = [
            (25_u8, self.latency_q1),
            (50_u8, self.latency_median),
            (75_u8, self.latency_q3),
        ];
        writeln!(f, "- distribution: {}", DistributionDisplay(&latency_distribution))?;
        writeln!(
            f,
            "- number of low outliers: {} ({:.2}%)",
            self.latency_nb_low_outliers, self.latency_percent_low_outliers
        )?;
        writeln!(
            f,
            "- number of high outliers: {} ({:.2}%)",
            self.latency_nb_high_outliers, self.latency_percent_high_outliers
        )?;
        writeln!(f, "{} requests/sec", self.rps)?;
        if let Some(transfer) = self.transfer {
            writeln!(f, "{:.2} MiB/sec", transfer)?;
        }
        Ok(())
    }
}

struct DistributionDisplay<'d>(&'d [(u8, f64)]);

impl fmt::Display for DistributionDisplay<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let distributions: Vec<String> = self
            .0
            .iter()
            .map(|(percent, time)| format!("{percent}% under {time:.3}ms"))
            .collect();

        f.write_str(&distributions.join("; "))
    }
}
