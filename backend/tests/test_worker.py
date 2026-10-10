from pytest import CaptureFixture

from repovil.worker import main


def test_worker_entry_point_starts(capsys: CaptureFixture[str]) -> None:
    main()

    output = capsys.readouterr()
    assert output.out == "Repovil worker is ready\n"

