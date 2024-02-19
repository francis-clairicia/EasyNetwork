from __future__ import annotations

import functools
import operator
import statistics
import typing


class RequestReport(typing.NamedTuple):
    start_time: float
    end_time: float

    def duration(self, *, resolution: int = 1) -> float:
        resolution = int(resolution)
        return (self.end_time - self.start_time) * resolution


class WorkerTestReport(typing.NamedTuple):
    times_per_request: list[RequestReport]
    messages_per_request: int

    def number_of_messages(self) -> int:
        return len(self.times_per_request) * self.messages_per_request

    def latency_stats(self) -> list[float]:
        return [r.duration(resolution=1_000) for r in self.times_per_request]

    def duration(self, *, resolution: int = 1) -> float:
        return sum(r.duration(resolution=resolution) for r in self.times_per_request)


class TestReport(typing.NamedTuple):
    message_size: int
    worker_reports: list[WorkerTestReport]

    def number_of_messages(self) -> int:
        return sum(report.number_of_messages() for report in self.worker_reports)

    def latency_stats(self) -> list[float]:
        return functools.reduce(operator.iadd, (report.latency_stats() for report in self.worker_reports), [])

    def duration(self) -> int:
        duration = statistics.mean(report.duration() for report in self.worker_reports)
        return int(duration)


class ReportDict(typing.TypedDict):
    messages: int
    latency_min: float
    latency_max: float
    latency_mean: float
    latency_stdev: float
    latency_q1: float
    latency_median: float
    latency_q3: float
    latency_nb_low_outliers: int
    latency_nb_high_outliers: int
    latency_percent_low_outliers: float
    latency_percent_high_outliers: float
    rps: int
    transfer: typing.NotRequired[float]


def dump_report(report: TestReport, *, show_transfer: bool = True) -> ReportDict:
    duration = report.duration()
    nb_messages = report.number_of_messages()
    message_size = report.message_size

    rps = int(nb_messages / duration)

    latency_stats = report.latency_stats()
    latency_stats.sort()

    latency_min = latency_stats[0]
    latency_max = latency_stats[-1]
    latency_mean = statistics.mean(latency_stats)
    latency_stdev = statistics.stdev(latency_stats, latency_mean)

    latency_first_quartile, latency_median, latency_third_quartile = statistics.quantiles(latency_stats, n=4)

    latency_iqr = latency_third_quartile - latency_first_quartile
    latency_lowerfence = latency_first_quartile - 1.5 * latency_iqr
    latency_upperfence = latency_third_quartile + 1.5 * latency_iqr

    latency_nb_low_outliers = sum(v < latency_lowerfence for v in latency_stats)
    latency_nb_high_outliers = sum(v > latency_upperfence for v in latency_stats)
    latency_percent_low_outliers = latency_nb_low_outliers / len(latency_stats)
    latency_percent_high_outliers = latency_nb_high_outliers / len(latency_stats)

    data: ReportDict = {
        "messages": nb_messages,
        "latency_min": round(latency_min, 3),
        "latency_max": round(latency_max, 3),
        "latency_mean": round(latency_mean, 3),
        "latency_stdev": round(latency_stdev, 3),
        "latency_q1": round(latency_first_quartile, 3),
        "latency_median": round(latency_median, 3),
        "latency_q3": round(latency_third_quartile, 3),
        "latency_nb_low_outliers": latency_nb_low_outliers,
        "latency_nb_high_outliers": latency_nb_high_outliers,
        "latency_percent_low_outliers": round(latency_percent_low_outliers * 100, 2),
        "latency_percent_high_outliers": round(latency_percent_high_outliers * 100, 2),
        "rps": rps,
    }

    if show_transfer:
        data["transfer"] = round((nb_messages * message_size / (1024 * 1024)) / duration, 2)

    return data


def print_report(report: TestReport, *, show_transfer: bool = True) -> None:
    result = dump_report(report, show_transfer=show_transfer)

    print("Report:")
    print(f"{result['messages']} (of {report.message_size / 1024:.2f} KiB size) in {report.duration()} seconds")
    print("Latency:")
    print(f"- min {result['latency_min']}ms")
    print(f"- max {result['latency_max']}ms")
    print(f"- mean {result['latency_mean']}ms")
    print(f"- std {result['latency_stdev']}ms ({100 * result['latency_stdev'] / result['latency_mean']:.2f}%)")
    latency_distribution = [
        (25, result["latency_q1"]),
        (50, result["latency_median"]),
        (75, result["latency_q3"]),
    ]
    print(f"- distribution: {'; '.join(f'{percent}% under {time}ms' for percent, time in latency_distribution)}")
    print(f"- number of low outliers: {result['latency_nb_low_outliers']} ({result['latency_percent_low_outliers']}%)")
    print(f"- number of high outliers: {result['latency_nb_high_outliers']} ({result['latency_percent_high_outliers']}%)")
    print(f"{result['rps']} requests/sec")
    if "transfer" in result:
        print(f"{result['transfer']} MiB/sec")
