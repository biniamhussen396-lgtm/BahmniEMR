'use strict';

angular.module('bahmni.common.domain')
    .service('localeService', ['$http', function ($http) {
        this.allowedLocalesList = function () {
            return $http.get(Bahmni.Common.Constants.globalPropertyUrl, {
                method: "GET",
                params: {
                    property: 'locale.allowed.list'
                },
                withCredentials: true,
                headers: {
                    Accept: 'text/plain'
                }
            });
        };

        this.defaultLocale = function () {
            return $http.get(Bahmni.Common.Constants.globalPropertyUrl, {
                method: "GET",
                params: {
                    property: 'default_locale'
                },
                withCredentials: true,
                headers: {
                    Accept: 'text/plain'
                }
            });
        };

        this.serverDateTime = function () {
            return $http.get(Bahmni.Common.Constants.serverDateTimeUrl, {
                method: "GET",
                ignoreErrors: true,
                headers: {
                    Accept: 'text/plain'
                }
            }).then(function (response) {
                if (response && response.data && response.data.date && Bahmni.Common.Util.DateUtil) {
                    Bahmni.Common.Util.DateUtil.setServerDateTime(response.data.date);
                }
                return response;
            }).catch(function (error) {
                console.warn('Unable to reach serverDateTimeUrl, using fallback date:', error);
                var fallbackDate = new Date().toISOString();
                if (Bahmni.Common.Util.DateUtil) {
                    Bahmni.Common.Util.DateUtil.setServerDateTime(fallbackDate);
                }
                return { data: { date: fallbackDate, offset: "+0000" } };
            });
        };

        this.getLoginText = function () {
            return $http.get(Bahmni.Common.Constants.loginText, {
                method: "GET",
                headers: {
                    Accept: 'text/plain'
                }
            });
        };

        this.getLocalesLangs = function () {
            return $http.get(Bahmni.Common.Constants.localeLangs, {
                method: "GET",
                headers: {
                    Accept: 'text/plain'
                }
            });
        };
    }]);
