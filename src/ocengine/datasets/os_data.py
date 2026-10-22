class macOSVersionInfo:
    """One macOS release paired with its fixed Darwin major version.

    Upstream derived ``darwin_version`` from the marketing string with three
    branches: ``minor + 4`` for "10.x", ``major + 9`` for anything starting with
    "1", ``major - 1`` otherwise. The prefix test conflated macOS 11 with a
    hypothetical macOS 16 and silently mis-mapped any unexpected value, so the
    known mapping is spelled out literally per release below. Darwin majors are
    data, not arithmetic: readable, reviewable, and identical on every import.
    """

    def __init__(self, name, macos_version, darwin_version, release_status = "final"):
        self.name = name
        self.darwin_version = darwin_version
        self.macos_version = macos_version
        self.release_status = release_status

macos_versions = [
    macOSVersionInfo("High Sierra", "10.13", darwin_version = 17),
    macOSVersionInfo("Mojave", "10.14", darwin_version = 18),
    macOSVersionInfo("Catalina", "10.15", darwin_version = 19),
    macOSVersionInfo("Big Sur", "11", darwin_version = 20),
    macOSVersionInfo("Monterey", "12", darwin_version = 21),
    macOSVersionInfo("Ventura", "13", darwin_version = 22),
    macOSVersionInfo("Sonoma", "14", darwin_version = 23),
    macOSVersionInfo("Sequoia", "15", darwin_version = 24),
    macOSVersionInfo("Tahoe", "26", darwin_version = 25)
]

def get_latest_darwin_version(include_beta=True):
    for macos_version in macos_versions[::-1]:
        if include_beta:
            return "{}.{}.{}".format(macos_version.darwin_version, 99, 99)
        else:
            if macos_version.release_status == "final":
                return "{}.{}.{}".format(macos_version.darwin_version, 99, 99)

def get_lowest_darwin_version():
    return "{}.{}.{}".format(macos_versions[0].darwin_version, 0, 0)

def get_macos_name_by_darwin(darwin_version):
    for data in macos_versions:
        if data.darwin_version == int(darwin_version[:2]):
            return "macOS {} {}{}".format(data.name, data.macos_version, "" if data.release_status == "final" else " (Beta)")
    return None
