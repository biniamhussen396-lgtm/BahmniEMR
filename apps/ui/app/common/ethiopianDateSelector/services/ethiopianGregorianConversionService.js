'use strict';

angular.module('bahmni.common.ethiopianDateSelector').factory('ethiopianGregorianService', function () {
    var months = ["መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"];

    var extractGregorianYearMonthDay = function (gregdate) {
        if (!gregdate) return null;
        var year, month, day;
        if (gregdate instanceof Date) {
            if (isNaN(gregdate.getTime())) return null;
            year = gregdate.getFullYear();
            month = gregdate.getMonth() + 1;
            day = gregdate.getDate();
        } else if (typeof gregdate === 'string') {
            gregdate = gregdate.trim();
            if (gregdate.indexOf('-') !== -1) {
                var datePart = gregdate.split('T')[0].split(' ')[0];
                var parts = datePart.split('-');
                if (parts.length === 3) {
                    if (parts[0].length === 4) { // YYYY-MM-DD
                        year = parseInt(parts[0], 10);
                        month = parseInt(parts[1], 10);
                        day = parseInt(parts[2], 10);
                    } else if (parts[2].length === 4) { // DD-MM-YYYY or MM-DD-YYYY
                        year = parseInt(parts[2], 10);
                        month = parseInt(parts[1], 10);
                        day = parseInt(parts[0], 10);
                    }
                }
            } else if (gregdate.indexOf('/') !== -1) {
                var parts = gregdate.split('/');
                if (parts.length === 3) {
                    if (parts[2].length === 4) { // MM/DD/YYYY or M/D/YYYY
                        year = parseInt(parts[2], 10);
                        month = parseInt(parts[0], 10);
                        day = parseInt(parts[1], 10);
                    } else if (parts[0].length === 4) { // YYYY/MM/DD
                        year = parseInt(parts[0], 10);
                        month = parseInt(parts[1], 10);
                        day = parseInt(parts[2], 10);
                    }
                }
            }
            if (!year || isNaN(year) || !month || isNaN(month) || !day || isNaN(day)) {
                var d = new Date(gregdate);
                if (!isNaN(d.getTime())) {
                    year = d.getFullYear();
                    month = d.getMonth() + 1;
                    day = d.getDate();
                }
            }
        }
        if (year && month && day && !isNaN(year) && !isNaN(month) && !isNaN(day)) {
            return { year: year, month: month, day: day };
        }
        return null;
    };

    // function used to convert from ethiopian date to gregorian date
    var ethToGreg = function (ethdate) {
        if (!ethdate) return null;
        var dmy = ethdate.toString().trim().split("/");
        if (dmy.length === 3) {
            try {
                var appdate = jQuery.calendars.instance('ethiopian').newDate(parseInt(dmy[2], 10), parseInt(dmy[1], 10), parseInt(dmy[0], 10));
                var jd = jQuery.calendars.instance('ethiopian').toJD(appdate);
                var appdategc = jQuery.calendars.instance('gregorian').fromJD(jd);
                return jQuery.calendars.instance('gregorian').formatDate('mm/dd/yyyy', appdategc);
            } catch (e) {
                return null;
            }
        }
        return null;
    };

    // function used to convert from gregorian date to ethiopian date
    var gregToEth = function (gregdate) {
        var ymd = extractGregorianYearMonthDay(gregdate);
        if (!ymd) return null;
        try {
            var appdate = jQuery.calendars.instance('gregorian').newDate(ymd.year, ymd.month, ymd.day);
            var jd = jQuery.calendars.instance('gregorian').toJD(appdate);
            var appdateet = jQuery.calendars.instance('ethiopian').fromJD(jd);
            return jQuery.calendars.instance('ethiopian').formatDate('dd/mm/yyyy', appdateet);
        } catch (e) {
            return null;
        }
    };

    // function used to convert from gregorian date to ethiopian date with textual month names
    var gregToEthMonthName = function (gregdate) {
        var ymd = extractGregorianYearMonthDay(gregdate);
        if (!ymd) return null;
        try {
            var appdate = jQuery.calendars.instance('gregorian').newDate(ymd.year, ymd.month, ymd.day);
            var jd = jQuery.calendars.instance('gregorian').toJD(appdate);
            var appdateet = jQuery.calendars.instance('ethiopian').fromJD(jd);
            return months[appdateet.month() - 1] + "/" + appdateet.day() + "/" + appdateet.year();
        } catch (e) {
            return null;
        }
    };

    return {
        gregToEth: gregToEth,
        ethToGreg: ethToGreg,
        gregToEthMonthName: gregToEthMonthName
    };
});
