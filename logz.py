import typing
import os
import re
import datetime
import time
from enum import Enum
from stringTools import ANSI_COLORS, ANSI_CLEAR_SCREEN


_timeExtractRe_str=r"""([=\s\(]|^)
(?P<value>[0-9]+([.][0-9]+)?)\s*
(?P<units>
    (((u|m)?s(ec)?)|((milli|micro)?sec(ond)?))|
    (m(in(ute)?)?)|
    (hr|hour)|
    (day)
)(s)?
([\s\)]|$)"""

_timeExtractRe_str=''.join(_timeExtractRe_str.split())
_timeExtractRe=re.compile(_timeExtractRe_str,re.DOTALL|re.MULTILINE|re.IGNORECASE)
def extractTiming(msg)->typing.Optional[datetime.timedelta]:
    """
    Any timing information found in the message Eg, "Process X took 120ms" extracts 120 milliseconds
    """
    ret=None
    for m in _timeExtractRe.finditer(msg):
        val=float(m.group('value'))
        units=m.group('units').lower()
        if units in ('hr','hour'):
            td=datetime.timedelta(hours=val)
        elif units in ('m','min','minute'):
            td=datetime.timedelta(minutes=val)
        elif units in ('ms','msec','millisecond'):
            td=datetime.timedelta(milliseconds=val)
        elif units in ('us','usec','microsecond'):
            td=datetime.timedelta(microseconds=val)
        elif units in ('s','sec','second'):
            td=datetime.timedelta(seconds=val)
        elif units=='day':
            td=datetime.timedelta(days=val)
        else:
            raise Exception(f'Unknown units "{units}"')
        if ret is None:
            ret=td
        else:
            ret+=td
    return ret

class LogLevel(Enum):
    ERROR = 1
    WARNING = 2
    DEBUG = 3

class LogMsg:
    def __init__(self,msg:str,level:LogLevel=LogLevel.DEBUG):
        self.level:LogLevel=level
        self._msg:str=''
        self.msg=msg

    @property
    def timing(self)->typing.Optional[datetime.timedelta]:
        """
        Any timing information found in the message Eg, "Process X took 120ms" extracts 120 milliseconds
        """
        return extractTiming(self.msg)
        
    def setMessage(self,msg,isCsv=None):
        """
        isCsv can be True,False or None to guess
        
        expected csv format:
        2022/01/04 09:15:42.318, user, domain, application, pid?, application type, ?? , ?? , ??, "message"
        """
        if isCsv is None:
            splitted=msg.split(',',9)
            if len(splitted)>9:
                isCsv=True
        elif isCsv:
            splitted=msg.split(',',9)
        if isCsv:
            #self.level=which field??
            self._msg=splitted[9].strip()[1:-1]
        else:
            self._msg=msg

    def __hash__(self):
        """
        The goal of the hash is to match the "same message"
        less any dynamically-changing values
        """
        numberless=[]
        for c in self.dataLine:
           if c.isalpha():
            numberless.append(c)
        return hash(''.join(numberless))
        
    def __repr__(self):
        return '%s: %s'%(self.level.name,self._msg)


class NotifyCallback:
    def __init__(self,
        fn:typing.Callable[[str],None],
        level:LogLevel=LogLevel.ERROR,
        matching:typing.Union[None,str,typing.Pattern]=None,
        notMatching:typing.Union[None,str,typing.Pattern]=None):
        """
        matching is applied first, then notMatching
        """
        self.fn:typing.Callable[[str],None]=fn
        self.level=level
        self.matching:typing.Union[None,str,typing.Pattern]=matching
        self.notMatching:typing.Union[None,str,typing.Pattern]=notMatching
        
    def logIfMatches(self,msg:LogMsg):
        if self.level.value>=msg.level.value:
            logit=False
            if self.matching is None:
                logit=True
            elif isinstance(self.matching,str):
                logit=msg.msg.find(self.matching)>=0
            else:
                logit=self.matching.match(msg.msg) is not None
            if logit and self.notMatching is not None:
                if isinstance(self.notMatching,str):
                    logit=msg.msg.find(self.matching)<0
                else:
                    logit=self.notMatching.match(msg.msg) is None
            if logit:       
                self.fn(msg)

class LogFileInfo:
    def __init__(self,filename:str):
        """
        maintain info about the log
        """
        self.filename=os.path.abspath(filename)
        self.modified=0
        self.size=0
        self.charsRead=0
        self.update()
        
    def __hash__(self):
        return hash(self.filename)
        
    def clear(self):
        """
        clear out this log file
        """
        f=open(self.filename,'wb')
        f.flush()
        f.close()
        self.update()
        
    def getNewLines(self)->typing.Iterable[str]:
        """
        get all of the new lines since last time this was called
        """
        ret=[]
        stat=os.stat(self.filename)
        if self.size!=stat.st_size or self.modified!=stat.st_mtime:
            f=open(self.filename,'rb')
            hasReset=self.size<stat.st_size
            self.size=stat.st_size
            self.modified=stat.st_mtime
            if hasReset:
                self.charsRead=0
            f.seek(self.charsRead)
            data=f.read()
            self.ret=data.decode('utf-8','ignore').split('\n')
            self.charsRead+=len(data)
        return ret
        
    def update(self):
        """
        get the updated info about the file
        """
        stat=os.stat(self.filename)
        self.size=stat.st_size
        self.modified=stat.st_mtime
        
    def hasChanged(self):
        """
        determine if it has changed since the last time hasChanged was called
        """
        stat=os.stat(self.filename)
        if self.size!=stat.st_size or self.modified!=stat.st_mtime:
            self.size=stat.st_size
            self.modified=stat.st_mtime
            return True
        return False
    

class Logz:
    def __init__(self,logfiles:typing.Iterable[str],notifyCallbacks:typing.Optional[typing.Iterable[NotifyCallback]]=None):
        if notifyCallbacks is None:
            notifyCallbacks=[]
        elif isinstance(notifyCallbacks,NotifyCallback):
            notifyCallbacks=[notifyCallbacks]
        self.notifyCallbacks:typing.List[NotifyCallback]=list(notifyCallbacks)
        self.waitSeconds=1.0
        self._logfiles:typing.List[LogFileInfo]=[]
        self.addLogfiles(logfiles)
        
    def addLogfiles(self,logfiles:typing.Union[str,typing.Iterable[str]]):
        """
        add one or more logfiles
        
        if the logfile ends in .logz then consider it a list of files to
        be opened and added individually.  if it is a directory, add all files in it.
        """
        added=set(self._logfiles)
        addedLogz=set()
        if isinstance(logfiles,str):
            logfiles=[logfiles]
        def recr(logfiles):
            for logfile in logfiles:
                logfile=logfile.strip()
                if not logfile:
                    continue
                if logfile.endswith('.logz'):
                    logfile=os.path.abspath(logfile)
                    if logfile not in addedLogz:
                        addedLogz.add(logfile)
                        f=open(logfile,'rb')
                        recr([line.strip() for line in f.read().decode('utf-8','ignore').split('\n')])
                elif os.path.isdir(logfile):
                    for f in os.listdir(logfile):
                        fullpath=logfile+os.sep+f
                        if os.path.isfile(fullpath):
                            recr([fullpath])
                else:
                    added.add(LogFileInfo(logfile))
        recr(logfiles)
        self._logfiles=list(added)
        
    def add(self,msg:LogMsg):
        """
        add a new message, calling all of the callbacks as necessary
        """
        for cb in self.notifyCallbacks:
            cb.logIfMatches(msg)
            
    def clearLogs(self):
        """
        clear out all of the log files - usually just before starting something
        """
        for logfile in self._logfiles:
            logfile.clear()
            
    def watch(self,autoClear=True):
        """
        runs forever, watching the logfiles and calling callbacks as necessary
        """
        if autoClear:
            self.clearLogs()
        while True:
            time.sleep(self.waitSeconds)
            for logfile in self._logfiles:
                lines=logfile.getNewLines()
                for line in lines:
                    line=LogMsg(line,ERROR) # TODO: figure this out somehow
                    self.add(line)
        
        
def consonsoleLog(logfiles:typing.Union[str,typing.Iterable[str]]):
    """
    quick console logger, displaying messages in grey,yellow,or red
    
    will watch forever
    """
    def logToCon(msg,LogMsg):
        color=ANSI_DARK_WHITE
        if msg.level==ERROR:
            color=ANSI_RED
        elif msg.level==WARNING:
            color=ANSI_YELLOW
        print('%s%s%s'%(color,msg.msg,ANSI_OFF))
    lz=Logz(logfiles,NotifyCallback(logToCon,LogLevel.DEBUG))
    lz.watch()
    

def cmdline(args:typing.Iterable[str])->int:
    filenames=[]
    for arg in args:
        if arg.startswith('-'):
            pass
        else:
            filenames.append(arg)
    consonsoleLog(filenames)
    return 0
   
   
if __name__=='__main__':
    import sys
    sys.exit(cmdline(sys.argv[1:]))