"""
Read log files in arbirtrary fixed-width formats
"""
import typing
import os
import datetime
from dateTools.dateRanges import DateRangeSimpleCompatible, DateRangeSimple
from paths import UrlCompatible,isURLCompatible,asURL,FileLocationCompatible,FileLocation,Url


class DateRangedFile(DateRangeSimple):
    """
    A file that also acts like a date range (created_date, modified_date)
    """
    def __init__(self,path:UrlCompatible):
        self.url:Url=asURL(path)
        filename=self.url.filePath
        if filename is None:
            # TODO: even throuh we can't limit by date, we should still allow this to be readable!
            raise Exception(f'Cannot get file time for an online url "{self.url}"')
        created=datetime.datetime.fromtimestamp(os.path.getctime(filename))
        modified=datetime.datetime.fromtimestamp(os.path.getmtime(filename))
        DateRangeSimple.__init__(self,(created,modified))
        print(f'File dates: {filename} = {self.start} - {self.end}')

    @property
    def created(self)->datetime.datetime:
        """
        What time the file was created.
        """
        return self.start
    @created.setter
    def created(self,created:datetime.datetime):
        self.start=created
    @property
    def modified(self)->datetime.datetime:
        """
        What time the file was last modified.
        """
        return self.end
    @created.setter
    def modified(self,modified:datetime.datetime):
        self.end=modified

    def read(self)->str:
        """
        Read the file
        """
        return self.url.read()


class DateRangedFiles:
    """
    A group of files where each also acts like a date range (created_date, modified_date) 
    """

    def __init__(self,filenames:typing.Union[UrlCompatible,typing.Iterable[UrlCompatible]]):
        self._files:typing.List[DateRangedFile]=[]
        self.assign(filenames)

    @property
    def files(self)->typing.Iterable[DateRangedFile]:
        """
        The files in this group
        """
        return self._files

    def assign(self,
        filenames:typing.Union[UrlCompatible,typing.Iterable[UrlCompatible]])->None:
        """
        Assign new files to this group, replacing any existing files
        """
        if isURLCompatible(filenames):
            filenames=(filenames,)
        self._files=[DateRangedFile(filename) for filename in filenames]

    def filter(self,
        dateRange:DateRangeSimpleCompatible)->typing.Generator[DateRangedFile,None,None]:
        """
        Filter the files in this group by a date range
        """
        for f in self._files:
            if f.overlaps(dateRange):
                yield f

class LogEntry:
    """
    A single log entry
    """
    def __init__(self,
        timestamp:datetime.datetime,
        msg:str,
        origin:typing.Optional[FileLocationCompatible]=None):
        """ """
        self.timestamp=timestamp
        self.msg=msg
        self.origin=origin

    def __int__(self):
        return int(self.timestamp.timestamp()*1000)
    def __float__(self):
        return self.timestamp.timestamp()
    def __lt__(self,other):
        return float(self)<float(other)
    def __repr__(self):
        msg=self.msg.replace('\t','    ')
        if self.origin is not None:
            return f'{self.origin}\t{self.timestamp}\t{msg}'
        return f'{self.timestamp}\t{msg}'

class LogFile(DateRangedFile):
    """
    A single log file
    """
    TOKEN_BREAKS=[' ']

    def __init__(self,path:UrlCompatible):
        DateRangedFile.__init__(self,path)
        self._logEntries:typing.Optional[typing.List[LogEntry]]=None

    @property
    def entries(self)->typing.Iterable[LogEntry]:
        """
        The log entries in this file
        """
        if self._logEntries is None:
            self.load()
        return self._logEntries

    def _getLineIndices(self,
        token:str,
        s:str,
        limit_by:typing.Optional[typing.List]=None
        )->typing.List[int]:
        """
        Get the indices of the token in the string,
        optionally limited by a list of indices to check
        """
        if limit_by is not None and not limit_by:
            return limit_by
        result:typing.List[int]=[]
        i=0
        for i in s.find(token,i):
            if i<0:
                break
            if limit_by is None or i in limit_by:
                result.append(i)
        return result

    def _getIndices(self,f:typing.Iterable[str])->typing.Iterable[typing.Tuple[int,str]]:
        """
        returns (index,char) for every splitting token
        """
        indices_per_token=[None for tb in self.TOKEN_BREAKS]
        for line in f:
            for i,tb in enumerate(self.TOKEN_BREAKS):
                indices_per_token[i]=self._getLineIndices(tb,line,indices_per_token[i])
        results:typing.List[typing.Tuple[int,str]]=[]
        for token,indices in zip(self.TOKEN_BREAKS,indices_per_token):
            for i in indices:
                results.append((i,token))
        results.sort()
        return results

    def load(self):
        """
        This will be called automatically as needed
        """
        # self._getIndices(f)
        for lineNo,line in enumerate(self.read().split('\n')):
            tsl=line.split(' dac1 ')
            if len(tsl)!=2:
                continue
            try:
                timestamp=datetime.datetime.strptime(tsl[0].strip(),"%m/%d/%y %H:%M:%S")
            except Exception:
                print(f'Unable to convert "{tsl[0]}" to date. Skipping line.')
                continue
            msg=tsl[1].rstrip()
            location=FileLocation(self.url,lineNo+1)
            self.entries.append(LogEntry(timestamp,msg,location))
        self.entries.sort()

    def filter(self,
        dateRange:typing.Optional[DateRangeSimpleCompatible]=None,
        matching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None,
        notMatching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None
        )->typing.Generator[LogEntry,None,None]:
        """
        must be in the dateRange if specified
        must be in one of matching if specified
        must not be in one of notMatching if specified
        """
        for entry in self.entries:
            if dateRange is not None:
                if entry.timestamp<dateRange[0] or entry.timestamp>dateRange[1]:
                    continue
            if matching is not None:
                found=False
                for m in matching:
                    if isinstance(m,str):
                        if entry.msg.find(m)>=0:
                            found=True
                            break
                if not found:
                    continue
            if notMatching is not None:
                found=False
                for m in notMatching:
                    if isinstance(m,str):
                        if entry.msg.find(m)>=0:
                            found=True
                            break
                if found:
                    continue
            yield entry

class Logjam(DateRangedFiles):
    """
    Read log files in arbirtrary fixed-width formats
    """

    def __init__(self,
        logfiles:typing.Union[UrlCompatible,typing.Iterable[UrlCompatible]],
        useFileDates:bool=False):
        """
        useFileDates: use the created/modified dates of the file for
            quick filtering entire files
        """
        self.useFileDates=useFileDates
        DateRangedFiles.__init__(self,logfiles)

    @property
    def entries(self)->typing.Iterable[LogEntry]:
        """
        This is the slowest way to access this object.

        Recommend to use filter() instead
        """
        ret=[]
        for logfile in self.files:
            ret.extend(logfile.entries)
        ret.sort()
        return ret

    def filterGen(self,
        dateRange:typing.Optional[DateRangeSimpleCompatible]=None,
        matching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None,
        notMatching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None
        )->typing.Generator[LogEntry,None,None]:
        """
        Slightly faster filter() function if you don't care about the results being in order

        must be in the dateRange if specified
        must be in one of matching if specified
        must not be in one of notMatching if specified

        NOTE: if you can filter by date, you should.  It can skip entire files!
        """
        if self.useFileDates and dateRange:
            logfiles=DateRangedFiles.filter(self,dateRange)
        else:
            logfiles=self.files
        for logfile in logfiles:
            yield from logfile.filter(dateRange,matching,notMatching)

    def filter(self,
        dateRange:typing.Optional[DateRangeSimpleCompatible]=None,
        matching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None,
        notMatching:typing.Optional[typing.Iterable[typing.Union[str,typing.Pattern]]]=None
        )->typing.Iterable[LogEntry]:
        """
        Like filterGen, but everything is in correct date order (at the cost of a slower function)

        must be in the dateRange if specified
        must be in one of matching if specified
        must not be in one of notMatching if specified

        NOTE: if you can filter by date, you should.  It can skip entire files!
        """
        ret=list(self.filterGen(dateRange,matching,notMatching))
        ret.sort()
        return ret
