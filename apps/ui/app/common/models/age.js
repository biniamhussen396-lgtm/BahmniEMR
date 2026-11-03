'use strict';

angular.module('bahmni.common.models')
    .factory('age', [function () {
        var dateUtil = Bahmni.Common.Util.DateUtil;

        var fromBirthDate = function (birthDate) {
            var today = dateUtil.now();
            var period = dateUtil.diffInYearsMonthsDays(birthDate, today);
            return create(period.years, period.months, period.days);
        };

        var create = function (years, months, days) {
            var isEmpty = function () {
                return !(this.years || this.months || this.days);
            };

            return {
                years: years,
                months: months,
                days: days,
                isEmpty: isEmpty
            };
        };

        var calculateBirthDate = function (age) {
            if (!age) return null;
            var years = parseInt(age.years, 10) || 0;
            var months = parseInt(age.months, 10) || 0;
            var days = parseInt(age.days, 10) || 0;

            if (years === 0 && months === 0 && days === 0) {
                return null;
            }

            var birthDate = dateUtil.now();
            if (years > 0) {
                birthDate = dateUtil.subtractYears(birthDate, years);
            }
            if (months > 0) {
                birthDate = dateUtil.subtractMonths(birthDate, months);
            }
            if (days > 0) {
                birthDate = dateUtil.subtractDays(birthDate, days);
            }
            return birthDate;
        };

        return {
            fromBirthDate: fromBirthDate,
            create: create,
            calculateBirthDate: calculateBirthDate
        };
    }]
);
