from __future__ import annotations

import typing


class RequestReport(typing.NamedTuple):
    start_time: float
    end_time: float

    def duration(self) -> float:
        return round(self.end_time - self.start_time, 2)


class WorkerTestReport(typing.NamedTuple):
    start_time: float
    end_time: float
    times_per_request: list[RequestReport]
    messages_per_request: int

    def number_of_messages(self) -> int:
        return len(self.times_per_request) * self.messages_per_request

    def latency_between_requests(self) -> float:
        whole_time = self.end_time - self.start_time
        request_time = sum(report.duration() for report in self.times_per_request)

        return max(whole_time - request_time, 0)


class TestReport(typing.NamedTuple):
    message_size: int
    worker_reports: list[WorkerTestReport]

    def number_of_messages(self) -> int:
        return sum(report.number_of_messages() for report in self.worker_reports)

    def start_time(self) -> float:
        return min(report.start_time for report in self.worker_reports)

    def end_time(self) -> float:
        return max(report.end_time for report in self.worker_reports)

    def latency_between_requests(self) -> float:
        return sum(report.latency_between_requests() for report in self.worker_reports)

    def duration(self) -> float:
        return round(self.end_time() - self.start_time(), 2)


class ReportDict(typing.TypedDict):
    messages: int
    rps: int
    transfer: typing.NotRequired[float]


def dump_report(report: TestReport, *, show_transfer: bool = True) -> ReportDict:
    duration = report.duration()
    nb_messages = report.number_of_messages()
    message_size = report.message_size

    rps = int(nb_messages / duration)
    transfer = round((nb_messages * message_size / (1024 * 1024)) / duration, 2) if show_transfer else None

    if transfer is None:
        return {
            "messages": nb_messages,
            "rps": rps,
        }

    return {
        "messages": nb_messages,
        "transfer": transfer,
        "rps": rps,
    }


def print_report(report: TestReport, *, show_transfer: bool = True) -> None:
    result = dump_report(report, show_transfer=show_transfer)

    print("Report:")
    print(f"{result['messages']} (of {report.message_size / 1024:.2f} KiB size) in {report.duration()} seconds")
    print(f"{result['rps']} requests/sec")
    if "transfer" in result:
        print(f"{result['transfer']} MiB/sec")
