'use strict';

angular.module('admin')
    .controller('BackupRestoreController', ['$scope', '$rootScope', '$http', '$interval', '$timeout', 'messagingService',
        function ($scope, $rootScope, $http, $interval, $timeout, messagingService) {
            $scope.backups = [];
            $scope.status = {
                status: 'idle',
                progress: 0,
                message: 'Loading...',
                logs: []
            };
            $scope.loading = true;
            $scope.selectedForDelete = null;
            $scope.deleteModalVisible = false;
            $scope.hasDeletePrivilege = false;

            $scope.activeConfigTab = 'schedule';
            $scope.autoConfig = {
                auto_backup: {
                    enabled: false,
                    frequency: 'daily',
                    time_of_day: '02:00',
                    day_of_week: 'Sunday',
                    backup_type: 'full',
                    retention_count: 7
                },
                external_drive: {
                    enabled: false,
                    path: '/media/usb',
                    retention_count: 7
                },
                remote_pc: {
                    enabled: false,
                    host: '',
                    port: 22,
                    username: '',
                    auth_type: 'password',
                    password: '',
                    remote_dir: '/var/backups/bahmni',
                    retention_count: 7
                }
            };
            $scope.savingConfig = false;
            $scope.testingExternal = false;
            $scope.externalTestResult = null;
            $scope.testingRemote = false;
            $scope.remoteTestResult = null;
            $scope.syncingNow = false;
            var pollPromise = null;

            var evaluatePrivileges = function () {
                var user = $rootScope.currentUser;
                if (!user) {
                    $scope.hasDeletePrivilege = false;
                    return;
                }
                var userPrivileges = _.map(user.privileges || [], function (p) {
                    return (p && p.name) ? p.name : p;
                });
                var userRoles = _.map(user.roles || [], function (r) {
                    return (r && r.name) ? r.name : r;
                });

                var isSuper = userRoles.indexOf('SuperAdmin') !== -1 ||
                              userRoles.indexOf('System Developer') !== -1 ||
                              userRoles.indexOf('Privilege Level: Full') !== -1 ||
                              (user.username && (user.username === 'admin' || user.username === 'superman'));

                if (isSuper ||
                    userPrivileges.indexOf('app:admin:deleteBackup') !== -1 ||
                    userPrivileges.indexOf('app:admin:delete') !== -1 ||
                    userPrivileges.indexOf('app:admin:backupRestore:delete') !== -1) {
                    $scope.hasDeletePrivilege = true;
                } else {
                    $scope.hasDeletePrivilege = false;
                }
            };

            evaluatePrivileges();
            $rootScope.$watch('currentUser', function (user) {
                if (user) {
                    evaluatePrivileges();
                }
            });

            var API_BASE = '/backup-api';

            $scope.fetchBackups = function () {
                $scope.loading = true;
                $http.get(API_BASE + '/backups').then(function (response) {
                    $scope.loading = false;
                    if (response.data && response.data.backups) {
                        $scope.backups = response.data.backups;
                    }
                    if (response.data && response.data.status) {
                        $scope.status = response.data.status;
                        if ($scope.status.status === 'running') {
                            startPolling();
                        }
                    }
                }, function (error) {
                    $scope.loading = false;
                    $scope.status.message = 'Unable to connect to Backup Service. Verify the service is running.';
                });
            };

            var pollStatus = function () {
                $http.get(API_BASE + '/status').then(function (response) {
                    $scope.status = response.data;
                    if ($scope.status.status !== 'running') {
                        stopPolling();
                        $scope.fetchBackups();
                        if ($scope.status.status === 'completed') {
                            messagingService.showMessage('info', 'Operation completed successfully!');
                        } else if ($scope.status.status === 'error') {
                            messagingService.showMessage('error', $scope.status.message || 'Operation encountered an error.');
                        }
                    }
                    // Auto-scroll logs
                    $timeout(function () {
                        var logBox = document.getElementById('backup-log-console');
                        if (logBox) {
                            logBox.scrollTop = logBox.scrollHeight;
                        }
                    }, 50);
                });
            };

            var startPolling = function () {
                if (!pollPromise) {
                    pollPromise = $interval(pollStatus, 2000);
                }
            };

            var stopPolling = function () {
                if (pollPromise) {
                    $interval.cancel(pollPromise);
                    pollPromise = null;
                }
            };

            $scope.startFullBackup = function () {
                if ($scope.status.status === 'running') return;
                $scope.status.status = 'running';
                $scope.status.progress = 5;
                $scope.status.message = 'Starting Full System Backup...';
                $scope.status.logs = ['[INFO] Starting Full System Backup (Databases, Volumes, Modules)...'];
                startPolling();

                $http.post(API_BASE + '/backup/full', {}).then(function (response) {
                    messagingService.showMessage('info', 'Full backup initiated.');
                }, function (err) {
                    stopPolling();
                    $scope.status.status = 'error';
                    var msg = (err.data && typeof err.data === 'object' && (err.data.message || err.data.error)) || 'Failed to start full backup. Backup Service is unreachable.';
                    $scope.status.message = msg;
                });
            };

            $scope.startDbBackup = function () {
                if ($scope.status.status === 'running') return;
                $scope.status.status = 'running';
                $scope.status.progress = 5;
                $scope.status.message = 'Starting Database Backup...';
                $scope.status.logs = ['[INFO] Starting Database Backup (OpenMRS, OpenELIS, Odoo, Reports, PACS)...'];
                startPolling();

                $http.post(API_BASE + '/backup/db', {}).then(function (response) {
                    messagingService.showMessage('info', 'Database backup initiated.');
                }, function (err) {
                    stopPolling();
                    $scope.status.status = 'error';
                    var msg = (err.data && typeof err.data === 'object' && (err.data.message || err.data.error)) || 'Failed to start database backup. Backup Service is unreachable.';
                    $scope.status.message = msg;
                });
            };

            $scope.confirmDelete = function (backup) {
                if (!$scope.hasDeletePrivilege) {
                    messagingService.showMessage('error', 'Access denied: You do not have permission to delete backup archives (app:admin:deleteBackup required).');
                    return;
                }
                if ($scope.status.status === 'running') {
                    messagingService.showMessage('warning', 'Cannot delete backups while an operation is in progress.');
                    return;
                }
                $scope.selectedForDelete = backup;
                $scope.deleteModalVisible = true;
            };

            $scope.cancelDelete = function () {
                $scope.selectedForDelete = null;
                $scope.deleteModalVisible = false;
            };

            $scope.executeDelete = function () {
                if (!$scope.selectedForDelete) return;
                if (!$scope.hasDeletePrivilege) {
                    messagingService.showMessage('error', 'Access denied: You do not have permission to delete backup archives (app:admin:deleteBackup required).');
                    return;
                }
                var backup = $scope.selectedForDelete;
                $scope.deleteModalVisible = false;
                $scope.loading = true;

                $http.post(API_BASE + '/backup/delete', {archive: backup.name}).then(function (response) {
                    $scope.loading = false;
                    messagingService.showMessage('info', 'Backup archive ' + backup.name + ' deleted successfully.');
                    $scope.fetchBackups();
                }, function (err) {
                    $scope.loading = false;
                    var errMsg = (err.data && err.data.error) || (err.data && err.data.message) || 'Failed to delete backup archive';
                    messagingService.showMessage('error', errMsg);
                });
            };

            $scope.getDownloadUrl = function (backup) {
                if (!backup || !backup.name) return '';
                return API_BASE + '/download/' + encodeURIComponent(backup.name);
            };

            $scope.fetchConfig = function () {
                $http.get(API_BASE + '/backup/config').then(function (res) {
                    if (res.data) {
                        $scope.autoConfig = res.data;
                    }
                }, function (err) {
                    // silent fallback
                });
            };

            $scope.saveConfig = function () {
                $scope.savingConfig = true;
                $http.post(API_BASE + '/backup/config', $scope.autoConfig).then(function (res) {
                    $scope.savingConfig = false;
                    if (res.data && res.data.config) {
                        $scope.autoConfig = res.data.config;
                    }
                    messagingService.showMessage('info', 'Auto-backup and storage destinations saved successfully.');
                }, function (err) {
                    $scope.savingConfig = false;
                    var msg = (err.data && err.data.error) || 'Failed to save configuration.';
                    messagingService.showMessage('error', msg);
                });
            };

            $scope.testExternalDrive = function () {
                $scope.testingExternal = true;
                $scope.externalTestResult = null;
                $http.post(API_BASE + '/backup/test-external', { path: $scope.autoConfig.external_drive.path }).then(function (res) {
                    $scope.testingExternal = false;
                    $scope.externalTestResult = { success: true, message: res.data.message };
                }, function (err) {
                    $scope.testingExternal = false;
                    var msg = (err.data && err.data.error) || 'External drive path test failed.';
                    $scope.externalTestResult = { success: false, message: msg };
                });
            };

            $scope.testRemotePC = function () {
                $scope.testingRemote = true;
                $scope.remoteTestResult = null;
                $http.post(API_BASE + '/backup/test-remote', $scope.autoConfig.remote_pc).then(function (res) {
                    $scope.testingRemote = false;
                    $scope.remoteTestResult = { success: true, message: res.data.message };
                }, function (err) {
                    $scope.testingRemote = false;
                    var msg = (err.data && err.data.error) || 'Remote connection test failed.';
                    $scope.remoteTestResult = { success: false, message: msg };
                });
            };

            $scope.syncAllDestinations = function () {
                $scope.syncingNow = true;
                $http.post(API_BASE + '/backup/sync-now', {}).then(function (res) {
                    $scope.syncingNow = false;
                    messagingService.showMessage('info', 'Synchronization to External Drive and Remote PC initiated.');
                    startPolling();
                }, function (err) {
                    $scope.syncingNow = false;
                    var msg = (err.data && err.data.error) || (err.data && err.data.message) || 'Failed to trigger synchronization.';
                    messagingService.showMessage('error', msg);
                });
            };

            $scope.$on('$destroy', function () {
                stopPolling();
            });

            // Initial load
            $scope.fetchBackups();
            $scope.fetchConfig();
        }
    ]);
