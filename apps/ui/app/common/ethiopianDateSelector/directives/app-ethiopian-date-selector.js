'use strict';

angular.module('bahmni.common.ethiopianDateSelector').directive('ethiopianDateSelector', ['ethiopianGregorianService', function (ethiopianGregorianService) {
    return {
        restrict: 'E',
        template: '<div class="field-value"><input type="text" ng-required="required" ng-disabled="disabled" placeholder="ቀን"/></div>',
        scope: {
            date: "=",
            handler: "&",
            required: "=?",
            disabled: "=?",
            minDate: "=?",
            maxDate: "=?",
            customMinDate: "=?",
            customMaxDate: "=?",
            allowFutureDates: "=?",
            change: "&",
            placeholder: "=?",
            handleUpdate: "&"
        },
        link: function (scope, element, attrs) {
            var inputElement = element.find('input');
            var DateUtil = Bahmni.Common.Util.DateUtil;
            var currentDate = new Date();
            var minDate = null;
            var maxDate = null;
            var isUpdatingFromInput = false;

            var safeApply = function (fn) {
                var phase = scope.$root ? scope.$root.$$phase : null;
                if (phase === '$apply' || phase === '$digest') {
                    if (fn && typeof fn === 'function') {
                        fn();
                    }
                } else {
                    scope.$apply(fn);
                }
            };

            if (scope.customMinDate) {
                minDate = new Date(currentDate);
                minDate.setDate(currentDate.getDate() - scope.customMinDate + 1);
                if (isNaN(minDate.getTime())) {
                    minDate = null;
                }
            } else {
                minDate = scope.minDate ? DateUtil.parse(scope.minDate) : null;
            }

            if (scope.allowFutureDates !== true && scope.customMaxDate) {
                maxDate = new Date(currentDate);
                maxDate.setDate(currentDate.getDate() - scope.customMaxDate);
                if (isNaN(maxDate.getTime())) {
                    maxDate = null;
                }
            } else {
                maxDate = scope.allowFutureDates ? null : currentDate;
            }

            var calendar = $.calendars.instance('ethiopian', 'am');

            var updateDateFromEthString = function (ethStr) {
                if (ethStr) {
                    var gregStr = ethiopianGregorianService.ethToGreg(ethStr);
                    if (gregStr) {
                        var greg = moment(gregStr, "M/D/YYYY").toDate();
                        if (!isNaN(greg.getTime())) {
                            scope.date = greg;
                            if (scope.handler) {
                                scope.handler();
                            }
                            if (scope.change) {
                                scope.change();
                            }
                            return;
                        }
                    }
                }
                scope.date = null;
                if (scope.handler) {
                    scope.handler();
                }
                if (scope.change) {
                    scope.change();
                }
            };

            inputElement.calendarsPicker({
                calendar: calendar,
                onSelect: function (dates) {
                    if (!dates || !dates[0]) return;
                    var ethDate = dates[0];
                    var eth = ethDate.day() + "/" + ethDate.month() + "/" + ethDate.year();
                    inputElement.val(eth);
                    safeApply(function () {
                        isUpdatingFromInput = true;
                        try {
                            updateDateFromEthString(eth);
                        } finally {
                            isUpdatingFromInput = false;
                        }
                    });
                },
                minDate: minDate ? ethiopianGregorianService.gregToEth(minDate) : null,
                maxDate: maxDate ? ethiopianGregorianService.gregToEth(maxDate) : null,
                holidays: Bahmni.Common.EthiopianDateSelector.constants.holidays
            });

            inputElement.on('change blur', function () {
                var ethVal = inputElement.val();
                safeApply(function () {
                    isUpdatingFromInput = true;
                    try {
                        updateDateFromEthString(ethVal);
                    } finally {
                        isUpdatingFromInput = false;
                    }
                });
            });

            scope.$watch('date', function (val) {
                if (isUpdatingFromInput) return;
                if (!val) {
                    inputElement.val('');
                    return;
                }
                var eth = ethiopianGregorianService.gregToEth(val);
                if (eth && inputElement.val() !== eth) {
                    inputElement.val(eth);
                }
            });

            if (scope.date && scope.handler) {
                scope.handler();
            }

            scope.updateObservation = function() {
                if (scope.handleUpdate) {
                    scope.handleUpdate();
                }
            };
        }
    };
}]).directive('ethiopianDateSelectorV2', ['ethiopianGregorianService', function (ethiopianGregorianService) {
    return {
        restrict: 'E',
        transclude: true,
        template: '<span ng-transclude></span>',
        scope: {
            date: "=",
            required: "=?",
            disabled: "=?",
            minDate: "=?",
            customMinDate: "=?",
            customMaxDate: "=?",
            allowFutureDates: "=?",
            handler: "&",
            change: "&"
        },
        link: function (scope, element, attrs) {
            var inputElement = element.find('input');
            var DateUtil = Bahmni.Common.Util.DateUtil;
            var currentDate = new Date();
            var minDate = null;
            var maxDate = null;
            var isUpdatingFromInput = false;

            var safeApply = function (fn) {
                var phase = scope.$root ? scope.$root.$$phase : null;
                if (phase === '$apply' || phase === '$digest') {
                    if (fn && typeof fn === 'function') {
                        fn();
                    }
                } else {
                    scope.$apply(fn);
                }
            };

            if (scope.customMinDate) {
                minDate = new Date(currentDate);
                minDate.setDate(currentDate.getDate() - scope.customMinDate);
                if (isNaN(minDate.getTime())) {
                    minDate = null;
                }
            } else {
                minDate = scope.minDate ? DateUtil.parse(scope.minDate) : null;
            }

            if (scope.allowFutureDates !== true && scope.customMaxDate) {
                maxDate = new Date(currentDate);
                maxDate.setDate(currentDate.getDate() - scope.customMaxDate);
                if (isNaN(maxDate.getTime())) {
                    maxDate = null;
                }
            } else {
                maxDate = scope.allowFutureDates ? null : currentDate;
            }
            var calendar = $.calendars.instance('ethiopian', 'am');

            var updateDateFromEthString = function (ethStr) {
                if (ethStr) {
                    var gregStr = ethiopianGregorianService.ethToGreg(ethStr);
                    if (gregStr) {
                        var greg = moment(gregStr, "M/D/YYYY").toDate();
                        if (!isNaN(greg.getTime())) {
                            scope.date = greg;
                            if (scope.handler) {
                                scope.handler();
                            }
                            if (scope.change) {
                                scope.change();
                            }
                            return;
                        }
                    }
                }
                scope.date = null;
                if (scope.handler) {
                    scope.handler();
                }
                if (scope.change) {
                    scope.change();
                }
            };

            inputElement.calendarsPicker({
                calendar: calendar,
                onSelect: function (dates) {
                    if (!dates || !dates[0]) return;
                    var ethDate = dates[0];
                    var eth = ethDate.day() + "/" + ethDate.month() + "/" + ethDate.year();
                    inputElement.val(eth);
                    safeApply(function () {
                        isUpdatingFromInput = true;
                        try {
                            updateDateFromEthString(eth);
                        } finally {
                            isUpdatingFromInput = false;
                        }
                    });
                },
                minDate: minDate ? ethiopianGregorianService.gregToEth(minDate) : null,
                maxDate: maxDate ? ethiopianGregorianService.gregToEth(maxDate) : null,
                holidays: Bahmni.Common.EthiopianDateSelector.constants.holidays
            });

            inputElement.on('change blur', function () {
                var ethVal = inputElement.val();
                safeApply(function () {
                    isUpdatingFromInput = true;
                    try {
                        updateDateFromEthString(ethVal);
                    } finally {
                        isUpdatingFromInput = false;
                    }
                });
            });

            scope.$watch('date', function (val) {
                if (isUpdatingFromInput) return;
                if (!val) {
                    inputElement.val('');
                    return;
                }
                var eth = ethiopianGregorianService.gregToEth(val);
                if (eth && inputElement.val() !== eth) {
                    inputElement.val(eth);
                }
            });

            if (scope.date && scope.handler) {
                scope.handler();
            }
        }
    };
}]).directive('ethiopianDateSelectorV3', ['ethiopianGregorianService', function (ethiopianGregorianService) {
    return {
        restrict: 'E',
        template: '<div class="field-value"><input type="text" /></div>',
        scope: {
            date: "=",
            handler: "=",
            handlerParam: "=",
            required: "=?",
            disabled: "=?",
            minDate: "=?",
            customMinDate: "=?",
            customMaxDate: "=?",
            allowFutureDates: "=?",
            change: "&"
        },
        link: function (scope, element, attrs) {
            var inputElement = element.find('input');
            var DateUtil = Bahmni.Common.Util.DateUtil;
            var currentDate = new Date();
            var minDate = null;
            var maxDate = null;
            var isUpdatingFromInput = false;

            var safeApply = function (fn) {
                var phase = scope.$root ? scope.$root.$$phase : null;
                if (phase === '$apply' || phase === '$digest') {
                    if (fn && typeof fn === 'function') {
                        fn();
                    }
                } else {
                    scope.$apply(fn);
                }
            };

            if (scope.customMinDate) {
                minDate = new Date(currentDate);
                minDate.setDate(currentDate.getDate() - scope.customMinDate);
                if (isNaN(minDate.getTime())) {
                    minDate = null;
                }
            } else {
                minDate = scope.minDate ? DateUtil.parse(scope.minDate) : null;
            }

            if (scope.allowFutureDates !== true && scope.customMaxDate) {
                maxDate = new Date(currentDate);
                maxDate.setDate(currentDate.getDate() - scope.customMaxDate);
                if (isNaN(maxDate.getTime())) {
                    maxDate = null;
                }
            } else {
                maxDate = scope.allowFutureDates ? null : currentDate;
            }
            var calendar = $.calendars.instance('ethiopian', 'am');

            var updateDateFromEthString = function (ethStr) {
                if (ethStr) {
                    var gregStr = ethiopianGregorianService.ethToGreg(ethStr);
                    if (gregStr) {
                        var greg = moment(gregStr, "M/D/YYYY").toDate();
                        if (!isNaN(greg.getTime())) {
                            scope.date = greg;
                            if (scope.handler) {
                                scope.handler(scope.handlerParam);
                            }
                            if (scope.change) {
                                scope.change();
                            }
                            return;
                        }
                    }
                }
                scope.date = null;
                if (scope.handler) {
                    scope.handler(scope.handlerParam);
                }
                if (scope.change) {
                    scope.change();
                }
            };

            inputElement.calendarsPicker({
                calendar: calendar,
                onSelect: function (dates) {
                    if (!dates || !dates[0]) return;
                    var ethDate = dates[0];
                    var eth = ethDate.day() + "/" + ethDate.month() + "/" + ethDate.year();
                    inputElement.val(eth);
                    safeApply(function () {
                        isUpdatingFromInput = true;
                        try {
                            updateDateFromEthString(eth);
                        } finally {
                            isUpdatingFromInput = false;
                        }
                    });
                },
                minDate: minDate ? ethiopianGregorianService.gregToEth(minDate) : null,
                maxDate: maxDate ? ethiopianGregorianService.gregToEth(maxDate) : null,
                holidays: Bahmni.Common.EthiopianDateSelector.constants.holidays
            });

            inputElement.on('change blur', function () {
                var ethVal = inputElement.val();
                safeApply(function () {
                    isUpdatingFromInput = true;
                    try {
                        updateDateFromEthString(ethVal);
                    } finally {
                        isUpdatingFromInput = false;
                    }
                });
            });

            scope.$watch('date', function (val) {
                if (isUpdatingFromInput) return;
                if (!val) {
                    inputElement.val('');
                    return;
                }
                var eth = ethiopianGregorianService.gregToEth(val);
                if (eth && inputElement.val() !== eth) {
                    inputElement.val(eth);
                }
            });

            if (scope.date && scope.handler) {
                scope.handler(scope.handlerParam);
            }
        }
    };
}]);
