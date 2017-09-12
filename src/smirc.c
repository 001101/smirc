/**
 * libsmirc
 * Copyright 2017
 * MIT License
 * smirc library wrapper
 **/
#include "smirc.h"
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdio.h>

extern int message(char* config, bool private, bool public, char* to, bool bot, char* message) {
    if ((message == NULL) || (message[0] == '\0')) {
        return NO_MESSAGE;
    }

    // exec, private, bool, public bool, bot, bool, message
    int cfg = 2;
    if (private) {
        cfg++;
    }
    if (public) {
        cfg++;
    }
    if (bot) {
        cfg++;
    }
    bool needConfig = false;
    bool needTo = false;
    if ((config == NULL) || (config[0] == '\0')) {
        // NOTE: no config passed, default
    } else {
        needConfig = true;
        cfg += 2;
    }

    if ((to == NULL) || (to[0] == '\0')) {
        // NOTE: no 'to' passed
    } else {
        needTo = true;
        cfg += 2;
    }

    char *args[cfg];
    int offset = 0;
    args[offset++] = "/usr/bin/smirc";
    if (private) {
        args[offset++] = "--private";
    }
    if (public) {
        args[offset++] = "--public";
    }
    if (bot) {
        args[offset++] = "--bot";
    }

    if (needConfig) {
        args[offset++] = "--config";
        args[offset++] = config;
    }

    if (needTo) {
        args[offset++] = "--to";
        args[offset++] = to;
    }

    args[offset] = message;

    // execute
    pid_t pid;
    int status;
    int timeout;
    if (0 == (pid = fork())) {
        if (-1 == execve(args[0], (char **)args , NULL)) {
            return CHILD_EXECVE;
        }
    }

    timeout = TIMEOUT;
    while (0 == waitpid(pid , &status , WNOHANG)) {
        if ( --timeout < 0 ) {
            return HIT_TIMEOUT;
        }
        sleep(1);
    }

    if (1 != WIFEXITED(status) || 0 != WEXITSTATUS(status)) {
        return EXECVE_FAILED;
    }

    return SUCCESS;
}
