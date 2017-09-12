/**
 * libsmirc
 * Copyright 2017
 * MIT License
 * Wraps 'smirc' call as a lib
 **/
#ifndef LIBSMIRC_H
#define LIBSMIRCME_H
#define NO_MESSAGE 1
#define SUCCESS 0
#define CHILD_EXECVE 2
#define EXECVE_FAILED 3
#define HIT_TIMEOUT 4

#define TIMEOUT 10
#include <stdbool.h>
extern int message(char*, bool, bool, char*, bool, char*);
#endif
