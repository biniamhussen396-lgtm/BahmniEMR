'use strict';

angular.module('bahmni.home')
    .controller('LoginLocationController', ['$rootScope', '$scope', '$window', '$location', '$http', 'sessionService', 'initialData', 'spinner', '$q', '$stateParams', '$bahmniCookieStore', 'localeService', '$translate', 'userService', 'auditLogService',
        function ($rootScope, $scope, $window, $location, $http, sessionService, initialData, spinner, $q, $stateParams, $bahmniCookieStore, localeService, $translate, userService, auditLogService) {
            var redirectUrl = $location.search()['from'];
            var landingPagePath = "/dashboard";
            var loginPagePath = "/login";
            const LOGIN_LOCATIONS = "Login Locations";
            $scope.loginInfo = {};
            var localeLanguages = [];

            var getLocalTimeZone = function () {
                var currentLocalTime = new Date().toString();
                var localTimeZoneList = currentLocalTime.split(" ");
                var localTimeZone = localTimeZoneList[localTimeZoneList.length - 1];
                localTimeZone = localTimeZone.substring(1, localTimeZone.length - 1);
                return localTimeZone;
            };

            var userLoginLocations = function () {
                var loginLocations = localStorage.getItem("loginLocations");
                return loginLocations ? JSON.parse(loginLocations) : [];
            };

            var identifyLoginLocations = function (allLocations) {
                var loginLocations = userLoginLocations();
                if (loginLocations.length === 0) {
                    return allLocations;
                }
                return loginLocations;
            };

            $scope.locations = identifyLoginLocations(initialData.locations);

            var findLanguageByLocale = function (localeCode) {
                return _.find(localeLanguages, function (localeLanguage) {
                    return localeLanguage.code == localeCode;
                });
            };

            var logAuditForLoginAttempts = function (eventType, isFailedEvent) {
                if ($scope.loginInfo.username) {
                    var messageParams = isFailedEvent ? {userName: $scope.loginInfo.username} : undefined;
                    auditLogService.log(undefined, eventType, messageParams, 'MODULE_LABEL_LOGIN_KEY');
                }
            };

            var promise = localeService.allowedLocalesList();
            localeService.serverDateTime().then(function (response) {
                var serverTime = response.data.date;
                var offset = response.data.offset;
                var localTime = new Date().toLocaleString();
                var localtimeZone = getLocalTimeZone();
                var localeTimeZone = localTime + " " + localtimeZone;
                $scope.timeZoneObject = { serverTime: serverTime, localeTimeZone: localeTimeZone};
                // Server date and time is enforced system-wide; no mismatch warning needed
            });

            // Branding saved from Admin -> Branding page wins over whiteLabel.json so the
            // login screen always reflects the latest save, regardless of which request lands last.
            var brandingApplied = false;

            localeService.getLoginText().then(function (response) {
                if (!brandingApplied) {
                    $scope.logo = response.data.loginPage.logo;
                    if (response.data.loginPage && response.data.loginPage.footerText) $scope.footerText = response.data.loginPage.footerText;
                    if (response.data.loginPage && response.data.loginPage.footerLink) $scope.footerLink = response.data.loginPage.footerLink;
                    if (response.data.loginPage && response.data.loginPage.footerLogo) $scope.footerLogo = response.data.loginPage.footerLogo;
                    if (response.data.homePage && response.data.homePage.browserTitle) $window.document.title = response.data.homePage.browserTitle;
                }
                $scope.bottomLogos = response.data.loginPage.bottomLogos;
                $scope.headerText = response.data.loginPage.showHeaderText;
                $scope.titleText = response.data.loginPage.showTitleText;
                $scope.helpLink = response.data.helpLink.url;
            });

            $http.get('/backup-api/branding', { ignoreErrors: true }).then(function (res) {
                var branding = res.data;
                if (!branding || !(branding.facilityName || branding.browserTitle)) {
                    return;
                }
                brandingApplied = true;
                if (branding.facilityName) $scope.brandingFacilityName = branding.facilityName;
                if (branding.tagline) $scope.brandingTagline = branding.tagline;
                if (branding.loginLogoUrl) $scope.logo = branding.loginLogoUrlWithCache || branding.loginLogoUrl;
                if (branding.footerText) $scope.footerText = branding.footerText;
                if (branding.footerLink) $scope.footerLink = branding.footerLink;
                if (branding.footerLogoUrl) $scope.footerLogo = branding.footerLogoUrlWithCache || branding.footerLogoUrl;
                if (branding.browserTitle) $window.document.title = branding.browserTitle;
            });

            localeService.getLocalesLangs().then(function (response) {
                localeLanguages = response.data.locales;
            }).finally(function () {
                promise.then(function (response) {
                    var localeList = response.data.replace(/\s+/g, '').split(',');
                    $scope.locales = [];
                    _.forEach(localeList, function (locale) {
                        var localeLanguage = findLanguageByLocale(locale);
                        if (_.isUndefined(localeLanguage)) {
                            $scope.locales.push({"code": locale, "nativeName": locale});
                        } else {
                            $scope.locales.push(localeLanguage);
                        }
                    });
                    $scope.selectedLocale = $translate.use() ? $translate.use() : $scope.locales[0].code;
                });
            });

            var getLoginLocationUuid = function () { return $bahmniCookieStore.get(Bahmni.Common.Constants.locationCookieName) ? $bahmniCookieStore.get(Bahmni.Common.Constants.locationCookieName).uuid : null; };

            var getLastLoggedinLocation = function () {
                return _.find(initialData.locations, function (location) {
                    return location.uuid === getLoginLocationUuid();
                });
            };

            $scope.loginInfo.currentLocation = getLastLoggedinLocation();

            if ($stateParams.showLoginMessage) {
                $scope.errorMessageTranslateKey = "LOGIN_LABEL_LOGIN_ERROR_MESSAGE_KEY";
            }

            var redirectToLandingPageIfAlreadyAuthenticated = function () {
                sessionService.get().then(function (data) {
                    if (data.authenticated) {
                        $location.path(landingPagePath);
                    }
                });
            };

            if ($location.path() === loginPagePath) {
                redirectToLandingPageIfAlreadyAuthenticated();
            }
            var onSuccessfulAuthentication = function () {
                $scope.loginInfo.currentLocation = getLastLoggedinLocation();
                $rootScope.$broadcast('event:auth-loggedin');
            };

            $scope.updateSessionLocation = function () {
                $scope.errorMessageTranslateKey = null;
                var deferrable = $q.defer();

                sessionService.updateSession($scope.loginInfo.currentLocation, null).then(function () {
                    sessionService.loadCredentials().then(function () {
                        onSuccessfulAuthentication();
                        userService.savePreferences().then(
                            function () { deferrable.resolve(); },
                            function (error) { deferrable.reject(error); }
                        );
                        logAuditForLoginAttempts("USER_LOGIN_LOCATION_SUCCESS");
                    }, function (error) {
                        $scope.errorMessageTranslateKey = error;
                        deferrable.reject(error);
                        logAuditForLoginAttempts("USER_LOGIN_LOCATION_FAILED", true);
                    });
                });

                spinner.forPromise(deferrable.promise).then(
                    function (data) {
                        if (data) return;
                        $location.url(landingPagePath);
                    }
                );
            };
        }]);
