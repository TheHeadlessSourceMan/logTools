"""
Watch log files and call callbacks when new lines are added
"""
import typing
import time
import threading
from paths import Url,UrlListCompatible,asUrlList,UrlCompatible


NewLogLinesFn=typing.Callable[[Url,typing.List[str]],None]


class _IndividualLogFileWatcher:
    """
    Represents an individual log watcher for a specific URL.
    """
    def __init__(self,url:UrlCompatible):
        """
        Initialize the IndividualLogWatcher.

        Args:
            url: The Url object representing the log file to watch.
        """
        self.url=Url(url)
        self.url.cache=False # turn off caching
        self._lastLogCount=0
        self._callbacks:typing.List[NewLogLinesFn]=[]
        self._lock=threading.Lock()
        self._pollInterval=0.2
        self._stopThread=False
        self._thread=threading.Thread(target=self._threadFn)
        self._thread.start()

    @property
    def numCallbacks(self)->int:
        """
        Get the number of registered callbacks.

        :return: The number of callbacks.
        """
        return len(self._callbacks)

    def add(self,
        newLogLinesFn:NewLogLinesFn,
        sendInitialLogLines:bool=False):
        """
        Add a new log lines callback.

        :param newLogLinesFn: The callback function to call when new lines
            are added.
        :param sendInitialLogLines: Whether to send the initial log lines
            immediately.
        """
        self._lock.acquire()
        # read the data
        data=list(self.url.readLines())
        self.url.close()
        count=len(data)
        # notify any current callbacks
        if count!=self._lastLogCount:
            if self._lastLogCount>count:
                self._onLogFileResetted()
            for callback in self._callbacks:
                callback(self.url,data[self._lastLogCount:])
            self._lastLogCount=count
        # add and optionally send everything to the new callback
        self._callbacks.append(newLogLinesFn)
        if sendInitialLogLines:
            newLogLinesFn(self.url,data)
        self._lock.release()

    def remove(self,
        newLogLinesFn:NewLogLinesFn):
        """
        Remove a log lines callback.

        :param newLogLinesFn: The callback function to remove.
        """
        with self._lock:
            if newLogLinesFn in self._callbacks:
                self._callbacks.remove(newLogLinesFn)

    def _onLogFileResetted(self):
        """
        Called when the log file is reset.
        """
        self._lastLogCount=0 # at minimum, start reading from the beginning
        print("Log file has been reset.")

    def _onFileChanged(self,url:Url):
        """
        Called when the watched file changes.
        Args:
            url: The Url object representing the changed file.
        """
        with self._lock:
            # Read the new lines from the log file
            data=list(self.url.readLines())
            self.url.close()
            count=len(data)
            if count!=self._lastLogCount:
                if self._lastLogCount>count:
                    self._onLogFileResetted()
                for callback in self._callbacks:
                    callback(url,data[self._lastLogCount-1:])
                self._lastLogCount=count

    def _threadFn(self):
        """
        Thread function that continuously checks for file changes.
        """
        from paths import FileUrl
        url=FileUrl(self.url)
        timestamp=url.lastModifiedTime
        filesize=url.fileSize
        while not getattr(self,"_stopThread",False):
            time.sleep(self._pollInterval)
            newTimestamp=url.lastModifiedTime
            newFilesize=url.fileSize
            if newTimestamp!=timestamp or newFilesize!=filesize:
                timestamp=newTimestamp
                filesize=newFilesize
                self._onFileChanged(url)

    def __del__(self):
        self._stopThread=True
        self._thread.join()


class LogWatcher:
    """
    Watch log files and call callbacks when new lines are added
    """

    # by using a global set, it ensures that we only have
    # one watcher per file
    _globalLogWatchers:typing.Dict[Url,_IndividualLogFileWatcher]={}

    def __init__(self,
        urls:UrlListCompatible,
        newLogLinesFn:typing.Optional[NewLogLinesFn],
        sendInitialLogLines:bool=False):
        """ """
        self._initial=newLogLinesFn
        if newLogLinesFn is not None:
            self.add(urls,newLogLinesFn,sendInitialLogLines)

    def add(self,
        urls:UrlListCompatible,
        newLogLinesFn:NewLogLinesFn,
        sendInitialLogLines:bool=False):
        """
        Add a new log lines callback.
        :param newLogLinesFn: The callback function to call when new
            lines are added.
        :param sendInitialLogLines: Whether to send the initial
        log lines immediately.
        """
        for url in asUrlList(urls):
            w=self._globalLogWatchers.get(url)
            if w is None:
                w=_IndividualLogFileWatcher(url)
                self._globalLogWatchers[url]=w
            w.add(newLogLinesFn,sendInitialLogLines)

    def remove(self,
        newLogLinesFn:typing.Optional[NewLogLinesFn]=None):
        """
        Remove a log lines callback.

        :param newLogLinesFn: The callback function to remove.
        """
        if newLogLinesFn is None:
            newLogLinesFn=self._initial
            self._initial=None
        if newLogLinesFn is None:
            return
        abandonedWatchers:typing.List[_IndividualLogFileWatcher]=[]
        for w in self._globalLogWatchers.values():
            w.remove(newLogLinesFn)
            if w.numCallbacks==0:
                abandonedWatchers.append(w)
        for w in abandonedWatchers:
            del self._globalLogWatchers[w.url]

    def __del__(self):
        self.remove()


def tail(
    urls:UrlListCompatible,
    sendInitialLogLines:bool=False,
    outputStream:typing.Optional[typing.TextIO]=None):
    """
    Run a console tail on the specified log files.

    :param urls: The log file URLs to watch.
    :param sendInitialLogLines: Whether to send the initial
        log lines immediately.
    :return: A LogWatcher instance.
    """
    if outputStream is None:
        import sys
        outputStream=sys.stdout
    def logTail(url:Url,lines:typing.List[str]):
        for line in lines:
            print(f"{url.name}: {line}",file=outputStream)
    lw=LogWatcher(urls,logTail,sendInitialLogLines)
    return lw


def cmdline(args:typing.Iterable[str])->int:
    """
    Run this like from the command line

    :param args: The command line arguments (excluding the script name).
    """
    logFiles:typing.List[str]=[]
    output=None
    printHelp=False
    sendInitialLogLines=False
    for arg in args:
        if arg.startswith('-'):
            arg=arg.split('=',1)
            arg[0]=arg[0].replace('-','').lower()
            if arg[0] in ('h','help'):
                printHelp=True
            if arg[0]=='sendinitialloglines':
                if len(arg)>1:
                    sendInitialLogLines=arg[1][0].lower() in ('1','t','y')
                else:
                    sendInitialLogLines=True
                sendInitialLogLines=True
            elif arg[0].startswith('--out'):
                if len(arg)>1:
                    output=Url(arg[1])
        else:
            logFiles.append(arg)
    if not logFiles:
        print("No log files specified.")
        printHelp=True
    else:
        tail(logFiles,
            sendInitialLogLines=sendInitialLogLines,
            outputStream=output)
        while True:
            time.sleep(1)
    if printHelp:
        print("Usage: script.py [--send-initial-log-lines] [--output=FILE] log_files...") # noqa: E501 # pylint: disable=line-too-long
        return -1
    return 0


if __name__=="__main__":
    import sys
    sys.exit(cmdline(sys.argv[1:]))
