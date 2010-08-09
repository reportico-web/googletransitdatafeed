#!/usr/bin/python2.5

# Copyright (C) 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import re
import time

import problems as problems_module
import util
from persistable import Persistable
from serviceperiodexception import ServicePeriodException

class ServicePeriod(object, Persistable):
  """Represents a service, which identifies a set of dates when one or more
  trips operate."""
  _DAYS_OF_WEEK = [
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    'saturday', 'sunday'
    ]
  _FIELD_NAMES_REQUIRED = [
    'service_id', 'start_date', 'end_date'
    ] + _DAYS_OF_WEEK
  _FIELD_NAMES = _FIELD_NAMES_REQUIRED  # no optional fields in this one

  _SQL_TABLENAME = "calendar"
  _SQL_FIELD_TYPES = ["CHAR(50)", "CHAR(8)", "CHAR(8)"] + 7*["INTEGER"]
  _SQL_FIELDS = zip( _FIELD_NAMES, _SQL_FIELD_TYPES )

  def __init__(self, id=None, field_list=None):
    Persistable.__init__(self, None)

    self.original_day_values = []
    if field_list:
      field_dict = dict( zip( self._FIELD_NAMES, field_list ) )

      self.service_id = field_dict[ 'service_id' ]
      self.day_of_week = [False] * len(self._DAYS_OF_WEEK)

      for index, day in enumerate( self._DAYS_OF_WEEK ):
        value = field_dict[ day ] or ''
        self.original_day_values += [value.strip()]
        self.day_of_week[index] = (value == u'1')

      self.start_date = field_dict[ 'start_date' ]
      self.end_date = field_dict[ 'end_date' ]
    else:
      self.service_id = id
      self.day_of_week = [False] * 7
      self.start_date = None
      self.end_date = None
    self.date_exceptions = {}  # Map from 'YYYYMMDD' to 1 (add) or 2 (remove)

  @property
  def start_date( self ):
    return self._start_date

  @start_date.setter
  def start_date( self, val ):
    self._start_date = val

    if self.cursor_factory is not None:
      if self._rowid is None:
        self.save()
      else:
        self.update( start_date=self._start_date )

  @property
  def end_date( self ):
    return self._end_date

  @end_date.setter
  def end_date( self, val ):
    self._end_date = val

    if self.cursor_factory is not None:
      if self._rowid is None:
        self.save()
      else:
        self.update( end_date=self._end_date )

  @property
  def service_id( self ):
    return self._service_id

  @service_id.setter
  def service_id( self, val ):
    self._service_id = val

    if self.cursor_factory is not None:
      if self._rowid is None:
        self.save()
      else:
        self.update( service_id=self._service_id )

  def _IsValidDate(self, date):
    if re.match('^\d{8}$', date) == None:
      return False

    try:
      time.strptime(date, "%Y%m%d")
      return True
    except ValueError:
      return False

  def HasExceptions(self):
    """Checks if the ServicePeriod has service exceptions."""

    # if this instance has no rowid, then SetDateHasService has never been called
    if self._rowid is None:
      return False

    query = "SELECT count(*) FROM calendar_dates WHERE service_period_rowid=?"

    cursor = self.cursor()
    cursor.execute( query, (self._rowid,) )
    return cursor.fetchone()[0] > 0 

  def GetDateRange(self):
    """Return the range over which this ServicePeriod is valid.

    The range includes exception dates that add service outside of
    (start_date, end_date), but doesn't shrink the range if exception
    dates take away service at the edges of the range.

    Returns:
      A tuple of "YYYYMMDD" strings, (start date, end date) or (None, None) if
      no dates have been given.
    """

    # if _rowid is None, then no exceptions have ever been registered
    if self._rowid is None:
      return self.start_date, self.end_date

    query = """SELECT min(low), max(high) 
                 FROM (
	           SELECT start_date AS low, end_date AS high 
		     FROM calendar 
		     WHERE rowid=? 
		   UNION select date AS low, date AS high 
		     FROM calendar_dates 
		     WHERE service_period_rowid=? 
		       AND exception_type=1)"""

    cursor = self.cursor()
    cursor.execute( query, (self._rowid,self._rowid) )
    return cursor.fetchone()

  def GetCalendarFieldValuesTuple(self):
    """Return the tuple of calendar.txt values or None if this ServicePeriod
    should not be in calendar.txt ."""
    if self.start_date and self.end_date:
      return [getattr(self, fn) for fn in self._FIELD_NAMES]

  def GenerateCalendarDatesFieldValuesTuples(self):
    """Generates tuples of calendar_dates.txt values. Yield zero tuples if
    this ServicePeriod should not be in calendar_dates.txt ."""
    for date, exception_type in self.date_exceptions.items():
      yield (self.service_id, date, unicode(exception_type))

  def GetCalendarDatesFieldValuesTuples(self):
    """Return a list of date execeptions"""
    result = []
    for date_tuple in self.GenerateCalendarDatesFieldValuesTuples():
      result.append(date_tuple)
    result.sort()  # helps with __eq__
    return result

  def SetDateHasService(self, date, has_service=True, problems=None):
    if date in self.date_exceptions and problems:
      problems.DuplicateID(('service_id', 'date'),
                           (self.service_id, date),
                           type=problems_module.TYPE_WARNING)

    # make sure we have a rowid
    if self._rowid is None:
      self.save()

    service_period_exception = ServicePeriodException( self.service_id, date, has_service and 1 or 2 )
    service_period_exception.cursor_factory = self.cursor_factory
    service_period_exception.save(service_period_rowid = self._rowid)

    self.date_exceptions[date] = has_service and 1 or 2

  def ResetDateToNormalService(self, date):
    if self._rowid is not None:
      ServicePeriodException.delete( self.cursor(), tolerant=True, service_period_rowid=self._rowid )

    if date in self.date_exceptions:
      del self.date_exceptions[date]

  def SetStartDate(self, start_date):
    """Set the first day of service as a string in YYYYMMDD format"""
    self.start_date = start_date

  def SetEndDate(self, end_date):
    """Set the last day of service as a string in YYYYMMDD format"""
    self.end_date = end_date

  def SetDayOfWeekHasService(self, dow, has_service=True):
    """Set service as running (or not) on a day of the week. By default the
    service does not run on any days.

    Args:
      dow: 0 for Monday through 6 for Sunday
      has_service: True if this service operates on dow, False if it does not.

    Returns:
      None
    """

    assert(dow >= 0 and dow < 7)

    if self._rowid is not None:
      self.update( **{self._DAYS_OF_WEEK[dow]:(1 if has_service else 0)} )

    self.day_of_week[dow] = has_service

  def SetWeekdayService(self, has_service=True):
    """Set service as running (or not) on all of Monday through Friday."""
    for i in range(0, 5):
      self.SetDayOfWeekHasService(i, has_service)

  def SetWeekendService(self, has_service=True):
    """Set service as running (or not) on Saturday and Sunday."""
    self.SetDayOfWeekHasService(5, has_service)
    self.SetDayOfWeekHasService(6, has_service)

  def SetServiceId(self, service_id):
    """Set the service_id for this schedule. Generally the default will
    suffice so you won't need to call this method."""
    self.service_id = service_id

  def IsActiveOn(self, date, date_object=None):
    """Test if this service period is active on a date.

    Args:
      date: a string of form "YYYYMMDD"
      date_object: a date object representing the same date as date.
                   This parameter is optional, and present only for performance
                   reasons.
                   If the caller constructs the date string from a date object
                   that date object can be passed directly, thus avoiding the 
                   costly conversion from string to date object.

    Returns:
      True iff this service is active on date.
    """
    if date in self.date_exceptions:
      if self.date_exceptions[date] == 1:
        return True
      else:
        return False
    if (self.start_date and self.end_date and self.start_date <= date and
        date <= self.end_date):
      if date_object is None:
        date_object = util.DateStringToDateObject(date)
      return self.day_of_week[date_object.weekday()]
    return False

  def ActiveDates(self):
    """Return dates this service period is active as a list of "YYYYMMDD"."""
    (earliest, latest) = self.GetDateRange()
    if earliest is None or latest is None:
      return []
    dates = []
    date_it = util.DateStringToDateObject(earliest)
    date_end = util.DateStringToDateObject(latest)
    delta = datetime.timedelta(days=1)
    while date_it <= date_end:
      date_it_string = date_it.strftime("%Y%m%d")
      if self.IsActiveOn(date_it_string, date_it):
        dates.append(date_it_string)
      date_it = date_it + delta
    return dates

  def __getattr__(self, name):
    try:
      # Return 1 if value in day_of_week is True, 0 otherwise
      return (self.day_of_week[self._DAYS_OF_WEEK.index(name)]
              and 1 or 0)
    except KeyError:
      pass
    except ValueError:  # not a day of the week
      pass
    raise AttributeError(name)

  def __getitem__(self, name):
    return getattr(self, name)

  def __eq__(self, other):
    if not other:
      return False

    if id(self) == id(other):
      return True

    if (self.GetCalendarFieldValuesTuple() !=
        other.GetCalendarFieldValuesTuple()):
      return False

    if (self.GetCalendarDatesFieldValuesTuples() !=
        other.GetCalendarDatesFieldValuesTuples()):
      return False

    return True

  def __ne__(self, other):
    return not self.__eq__(other)

  def ValidateServiceId(self, problems):
    if util.IsEmpty(self.service_id):
      problems.MissingValue('service_id')

  def ValidateStartDate(self, problems):
    if self.start_date is not None:
      if util.IsEmpty(self.start_date):
        problems.MissingValue('start_date')
        self.start_date = None
      elif not self._IsValidDate(self.start_date):
        problems.InvalidValue('start_date', self.start_date)
        self.start_date = None

  def ValidateEndDate(self, problems):
    if self.end_date is not None:
      if util.IsEmpty(self.end_date):
        problems.MissingValue('end_date')
        self.end_date = None
      elif not self._IsValidDate(self.end_date):
        problems.InvalidValue('end_date', self.end_date)
        self.end_date = None

  def ValidateEndDateAfterStartDate(self, problems):
    if self.start_date and self.end_date and self.end_date < self.start_date:
      problems.InvalidValue('end_date', self.end_date,
                            'end_date of %s is earlier than '
                            'start_date of "%s"' %
                            (self.end_date, self.start_date))

  def ValidateDaysOfWeek(self, problems):
    if self.original_day_values:
      for column_name, value in zip( self._DAYS_OF_WEEK, self.original_day_values ):
        if util.IsEmpty(value):
          problems.MissingValue(column_name)
        elif (value != u'0') and (value != '1'):
          problems.InvalidValue(column_name, value)

  def ValidateHasServiceAtLeastOnceAWeek(self, problems):
    if (True not in self.day_of_week and
        1 not in self.date_exceptions.values()):
      problems.OtherProblem('Service period with service_id "%s" '
                            'doesn\'t have service on any days '
                            'of the week.' % self.service_id,
                            type=problems_module.TYPE_WARNING)

  def ValidateDates(self, problems):
    for date in self.date_exceptions:
      if not self._IsValidDate(date):
        problems.InvalidValue('date', date)

  def Validate(self, problems=problems_module.default_problem_reporter):

    self.ValidateServiceId(problems)

    # self.start_date/self.end_date is None in 3 cases:
    # ServicePeriod created by loader and
    #   1a) self.service_id wasn't in calendar.txt
    #   1b) calendar.txt didn't have a start_date/end_date column
    # ServicePeriod created directly and
    #   2) start_date/end_date wasn't set
    # In case 1a no problem is reported. In case 1b the missing required column
    # generates an error in _ReadCSV so this method should not report another
    # problem. There is no way to tell the difference between cases 1b and 2
    # so case 2 is ignored because making the feedvalidator pretty is more
    # important than perfect validation when an API users makes a mistake.
    self.ValidateStartDate(problems)
    self.ValidateEndDate(problems)

    self.ValidateEndDateAfterStartDate(problems)
    self.ValidateDaysOfWeek(problems)
    self.ValidateHasServiceAtLeastOnceAWeek(problems)
    self.ValidateDates(problems)
