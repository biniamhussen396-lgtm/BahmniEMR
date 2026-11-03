'use strict';

angular.module('admin')
    .controller('BrandingController', ['$scope', '$rootScope', '$http', '$timeout', 'messagingService',
        function ($scope, $rootScope, $http, $timeout, messagingService) {
            var API_BASE = '/backup-api';

            $scope.loading = true;
            $scope.saving = false;
            $scope.savedSuccess = false;
            $scope.activePreview = 'login'; // 'login', 'header', 'print'
            $scope.applyMainLogoToAll = true;

            $scope.branding = {
                facilityName: 'Boru Meda General Hospital',
                tagline: 'General Hospital EMR System',
                welcomeMessage: 'WELCOME TO BORU MEDA GENERAL HOSPITAL EMR System',
                address: 'Boru Meda, Dessie, Amhara, Ethiopia',
                phone: '+251 33 111 2233',
                email: 'info@borumedahospital.gov.et',
                website: 'www.borumedahospital.gov.et',
                browserTitle: 'BMH bahmni',
                mainLogoUrl: '/bahmni/images/bahmniLogo.png',
                loginLogoUrl: '/bahmni_config/openmrs/apps/home/logo.png',
                printLogoUrl: '/bahmni_config/openmrs/apps/registration/registrationCardLayout/images/bahmni-icon.png',
                faviconUrl: '/bahmni/favicon.ico',
                footerLogoUrl: '/bahmni/images/cdhiLogo.png',
                footerText: 'powered by CDHi',
                footerLink: 'https://cdhi.uog.edu.et/'
            };

            $scope.previews = {
                mainLogo: null,
                loginLogo: null,
                printLogo: null,
                favicon: null,
                footerLogo: null
            };

            $scope.payload = {
                mainLogoBase64: null,
                loginLogoBase64: null,
                printLogoBase64: null,
                faviconBase64: null,
                footerLogoBase64: null
            };

            $scope.fetchBranding = function () {
                $scope.loading = true;
                $http.get(API_BASE + '/branding').then(function (res) {
                    $scope.loading = false;
                    if (res.data) {
                        $scope.branding = res.data;
                        $scope.previews.mainLogo = res.data.mainLogoUrlWithCache || res.data.mainLogoUrl;
                        $scope.previews.loginLogo = res.data.loginLogoUrlWithCache || res.data.loginLogoUrl;
                        $scope.previews.printLogo = res.data.printLogoUrlWithCache || res.data.printLogoUrl;
                        $scope.previews.favicon = res.data.faviconUrlWithCache || res.data.faviconUrl;
                        $scope.previews.footerLogo = res.data.footerLogoUrlWithCache || res.data.footerLogoUrl;
                    }
                }, function (err) {
                    $scope.loading = false;
                    // Fallback to defaults
                });
            };

            var readFileAsDataURL = function (file, callback) {
                var reader = new FileReader();
                reader.onload = function (e) {
                    $scope.$apply(function () {
                        callback(e.target.result);
                    });
                };
                reader.readAsDataURL(file);
            };

            $scope.onMainLogoSelected = function (element) {
                if (element.files && element.files[0]) {
                    readFileAsDataURL(element.files[0], function (dataUrl) {
                        $scope.previews.mainLogo = dataUrl;
                        $scope.payload.mainLogoBase64 = dataUrl;
                        if ($scope.applyMainLogoToAll) {
                            $scope.previews.loginLogo = dataUrl;
                            $scope.payload.loginLogoBase64 = dataUrl;
                            $scope.previews.printLogo = dataUrl;
                            $scope.payload.printLogoBase64 = dataUrl;
                        }
                    });
                }
            };

            $scope.onLoginLogoSelected = function (element) {
                if (element.files && element.files[0]) {
                    readFileAsDataURL(element.files[0], function (dataUrl) {
                        $scope.previews.loginLogo = dataUrl;
                        $scope.payload.loginLogoBase64 = dataUrl;
                        $scope.applyMainLogoToAll = false;
                    });
                }
            };

            $scope.onPrintLogoSelected = function (element) {
                if (element.files && element.files[0]) {
                    readFileAsDataURL(element.files[0], function (dataUrl) {
                        $scope.previews.printLogo = dataUrl;
                        $scope.payload.printLogoBase64 = dataUrl;
                        $scope.applyMainLogoToAll = false;
                    });
                }
            };

            $scope.onFaviconSelected = function (element) {
                if (element.files && element.files[0]) {
                    readFileAsDataURL(element.files[0], function (dataUrl) {
                        $scope.previews.favicon = dataUrl;
                        $scope.payload.faviconBase64 = dataUrl;
                    });
                }
            };

            $scope.onFooterLogoSelected = function (element) {
                if (element.files && element.files[0]) {
                    readFileAsDataURL(element.files[0], function (dataUrl) {
                        $scope.previews.footerLogo = dataUrl;
                        $scope.payload.footerLogoBase64 = dataUrl;
                    });
                }
            };

            $scope.saveBranding = function () {
                if (!$scope.branding.facilityName) {
                    messagingService.showMessage('error', 'Facility / Hospital name cannot be empty.');
                    return;
                }

                $scope.saving = true;
                $scope.savedSuccess = false;

                var dataToSend = {
                    facilityName: $scope.branding.facilityName,
                    tagline: $scope.branding.tagline,
                    welcomeMessage: $scope.branding.welcomeMessage,
                    address: $scope.branding.address,
                    phone: $scope.branding.phone,
                    email: $scope.branding.email,
                    website: $scope.branding.website,
                    browserTitle: $scope.branding.browserTitle,
                    footerText: $scope.branding.footerText,
                    footerLink: $scope.branding.footerLink,
                    applyMainLogoToAll: $scope.applyMainLogoToAll,
                    mainLogoBase64: $scope.payload.mainLogoBase64,
                    loginLogoBase64: $scope.payload.loginLogoBase64,
                    printLogoBase64: $scope.payload.printLogoBase64,
                    faviconBase64: $scope.payload.faviconBase64,
                    footerLogoBase64: $scope.payload.footerLogoBase64
                };

                $http.post(API_BASE + '/branding', dataToSend).then(function (res) {
                    $scope.saving = false;
                    $scope.savedSuccess = true;
                    if (res.data && res.data.branding) {
                        $scope.branding = res.data.branding;
                    }
                    $scope.payload = {
                        mainLogoBase64: null,
                        loginLogoBase64: null,
                        printLogoBase64: null,
                        faviconBase64: null,
                        footerLogoBase64: null
                    };
                    messagingService.showMessage('info', 'Hospital branding and logos updated successfully across all pages and print documents!');
                    $timeout(function () {
                        $scope.savedSuccess = false;
                    }, 5000);
                }, function (err) {
                    $scope.saving = false;
                    var msg = (err.data && err.data.error) || 'Failed to save branding configuration.';
                    messagingService.showMessage('error', msg);
                });
            };

            $scope.fetchBranding();
        }
    ]);
