'use strict';

angular.module('bahmni.common.uiHelper').service('ethiopianConvert', ['ethiopianGregorianService', function (ethiopianGregorianService) {
    this.toEthiopian = function (date, format) {
        var ethDate = "";
        if (date == null) return ethDate;
        var dateRepresentation = isNaN(Number(date)) ? date : Number(date);
        if (format) {
            if (moment(dateRepresentation, format).isValid()) {
                var jsDate = moment(dateRepresentation, format).toDate();
                var string = (jsDate.getMonth() + 1) + "/" + jsDate.getDate() + "/" + jsDate.getFullYear();
                ethDate = " (" + ethiopianGregorianService.gregToEthMonthName(string) + ")";
            }
        }
        else {
            if (moment(dateRepresentation).isValid()) {
                var jsDate = moment(dateRepresentation).toDate();
                var string = (jsDate.getMonth() + 1) + "/" + jsDate.getDate() + "/" + jsDate.getFullYear();
                ethDate = " (" + ethiopianGregorianService.gregToEthMonthName(string) + ")";
            }
        }
        return ethDate;
    };
    this.toEthiopianWithDays = function (date) {
        var ethDate = "";
        if (date == null) return ethDate;
        var dateRep = ["DD/MM/YYYY", "MM/DD/YYYY", "DD-MM-YYYY", "MM-DD-YYYY"];
        var daysEth = ['እሑድ', 'ሰኞ', 'ማክሰኞ', 'ረቡዕ', 'ሓሙስ', 'ዓርብ', 'ቅዳሜ'];
        var dateRepresentation = isNaN(Number(date)) ? date : Number(date);
        if (moment(dateRepresentation).isValid() || moment(dateRepresentation, dateRep).isValid()) {
            var jsDate = moment(dateRepresentation).isValid() ? moment(dateRepresentation).toDate() : moment(dateRepresentation, dateRep).toDate();
            var string = (jsDate.getMonth() + 1) + "/" + jsDate.getDate() + "/" + jsDate.getFullYear();
            ethDate = daysEth[jsDate.getDay()] + ", " + ethiopianGregorianService.gregToEthMonthName(string);
        }
        return ethDate;
    };
}]).filter('days', function () {
    return function (startDate, endDate) {
        return Bahmni.Common.Util.DateUtil.diffInDays(startDate, endDate);
    };
}).filter('bahmniDateTime', function () {
    return function (date) {
        return Bahmni.Common.Util.DateUtil.formatDateWithTime(date);
    };
}).filter('bahmniDate', function () {
    return function (date) {
        return Bahmni.Common.Util.DateUtil.formatDateWithoutTime(date);
    };
}).filter('bahmniTime', function () {
    return function (date) {
        return Bahmni.Common.Util.DateUtil.formatTime(date);
    };
}).filter('bahmniDateInStrictMode', function () {
    return function (date) {
        return Bahmni.Common.Util.DateUtil.formatDateInStrictMode(date);
    };
}).filter('bahmniDateTimeWithFormat', function () {
    return function (date, format) {
        return Bahmni.Common.Util.DateUtil.getDateTimeInSpecifiedFormat(date, format);
    };
}).filter('addDays', function () {
    return function (date, numberOfDays) {
        return Bahmni.Common.Util.DateUtil.addDays(date, numberOfDays);
    };
}).filter('days', function () {
    return function (startDate, endDate) {
        return Bahmni.Common.Util.DateUtil.diffInDays(startDate, endDate);
    };
}).filter('bahmniDateTime', ['ethiopianConvert', function (ethiopianConvert) {
    return function (date) {
        if (date) {
            var formated = Bahmni.Common.Util.DateUtil.formatDateWithTime(date);
            formated += ethiopianConvert.toEthiopian(date);
            return formated;
        }
        return date;
    };
}]).filter('bahmniDate', ['ethiopianConvert', function (ethiopianConvert) {
    return function (date) {
        if (date) {
            var formated = Bahmni.Common.Util.DateUtil.formatDateWithoutTime(date);
            formated += ethiopianConvert.toEthiopian(date);
            return formated;
        }
        return date;
    };
}]).filter('bahmniDateWithFormat', ['ethiopianConvert', function (ethiopianConvert) {
    return function (date, format) {
        var parsed = Bahmni.Common.Util.DateUtil.parseUsingFormat(date, format);
        var formated = Bahmni.Common.Util.DateUtil.formatDateWithoutTime(parsed);
        formated += ethiopianConvert.toEthiopian(date, format);

        return formated;
    };
}]).filter('bahmniTime', function () {
    return function (date) {
        return Bahmni.Common.Util.DateUtil.formatTime(date);
    };
}).filter('bahmniDateInStrictMode', ['ethiopianConvert', function (ethiopianConvert) {
    return function (date) {
        if (date) {
            var formated = Bahmni.Common.Util.DateUtil.formatDateInStrictMode(date);
            formated += ethiopianConvert.toEthiopian(date);

            return formated;
        }
        return '';
    };
}]).filter('bahmniCalDate', ['ethiopianConvert', function (ethiopianConvert) {
    return function (date) {
        if (date) {
            var formated = ethiopianConvert.toEthiopianWithDays(date);
            return formated;
        }
        return date;
    };
}]);

angular.module('bahmni.common.uiHelper').directive('serverDateTimeHeader', ['$interval', function ($interval) {
    return {
        restrict: 'EA',
        replace: true,
        scope: {},
        template: '<div class="server-datetime-header-widget" style="display:inline-flex;align-items:center;vertical-align:middle;margin:3px 10px;padding:3px 12px;background:rgba(0,0,0,0.25);border:1px solid rgba(255,255,255,0.22);border-radius:18px;font-family:Segoe UI,OpenSans,Arial,sans-serif;font-size:12px;color:#fff;box-shadow:inset 0 1px 3px rgba(0,0,0,0.2);line-height:22px;z-index:99;white-space:nowrap;">' +
            '<span style="color:#b2dfdb;font-weight:700;display:inline-flex;align-items:center;gap:4px;margin-right:8px;">' +
                '<i class="fa fa-calendar-check-o" style="color:#80cbc4;"></i> <span style="font-size:10px;padding:1px 5px;background:rgba(255,255,255,0.15);border-radius:4px;color:#ffffff;letter-spacing:0.5px;font-weight:bold;">GC</span> <span style="color:#ffffff;font-weight:600;letter-spacing:0.2px;">{{serverTime.gc}}</span>' +
            '</span>' +
            '<span style="color:rgba(255,255,255,0.35);margin-right:8px;">|</span>' +
            '<span style="color:#ffe0b2;font-weight:700;display:inline-flex;align-items:center;gap:4px;">' +
                '<i class="fa fa-clock-o" style="color:#ffcc80;"></i> <span style="font-size:10px;padding:1px 5px;background:rgba(255,255,255,0.15);border-radius:4px;color:#ffffff;letter-spacing:0.5px;font-weight:bold;">EC</span> <span style="color:#ffffff;font-weight:600;letter-spacing:0.2px;">{{serverTime.ec}}</span>' +
            '</span>' +
        '</div>',
        link: function (scope) {
            var monthsEn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            var daysEn = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

            function pad(n) { return n < 10 ? '0' + n : '' + n; }

            function update() {
                var now = (Bahmni && Bahmni.Common && Bahmni.Common.Util && Bahmni.Common.Util.DateUtil && typeof Bahmni.Common.Util.DateUtil.now === 'function')
                    ? Bahmni.Common.Util.DateUtil.now()
                    : new Date();

                var h = now.getHours();
                var m = pad(now.getMinutes());
                var s = pad(now.getSeconds());
                var ampm = h >= 12 ? 'PM' : 'AM';
                var h12 = h % 12 || 12;
                var timeStr = pad(h12) + ':' + m + ':' + s + ' ' + ampm;

                var gcStr = daysEn[now.getDay()] + ', ' + monthsEn[now.getMonth()] + ' ' + pad(now.getDate()) + ', ' + now.getFullYear() + ' ' + timeStr;
                
                var ecStr = '';
                if (Bahmni.Common.Util.DateUtil && typeof Bahmni.Common.Util.DateUtil.toEthiopian === 'function') {
                    var eth = Bahmni.Common.Util.DateUtil.toEthiopian(now);
                    if (eth) {
                        ecStr = eth.monthName + ' ' + eth.day + ', ' + eth.year + ' (' + eth.formatted + ') ' + timeStr;
                    }
                }

                scope.serverTime = {
                    gc: gcStr,
                    ec: ecStr
                };
            }

            update();
            var timer = $interval(update, 1000);
            scope.$on('$destroy', function () {
                if (timer) $interval.cancel(timer);
            });
        }
    };
}]);
