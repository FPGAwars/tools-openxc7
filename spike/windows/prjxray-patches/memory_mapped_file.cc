/*
 * Copyright (C) 2017-2020  The Project X-Ray Authors.
 *
 * Use of this source code is governed by a ISC-style
 * license that can be found in the LICENSE file or at
 * https://opensource.org/licenses/ISC
 *
 * SPDX-License-Identifier: ISC
 */
#include <prjxray/memory_mapped_file.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#endif

namespace prjxray {

std::unique_ptr<MemoryMappedFile> MemoryMappedFile::InitWithFile(
    const std::string& path) {
#ifdef _WIN32
	HANDLE file = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ,
	                          NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
	                          NULL);
	if (file == INVALID_HANDLE_VALUE)
		return nullptr;

	LARGE_INTEGER file_size;
	if (!GetFileSizeEx(file, &file_size)) {
		CloseHandle(file);
		return nullptr;
	}

	// A zero-length file cannot be mapped; return an object (to indicate
	// the file exists) with a nullptr and zero length.
	if (file_size.QuadPart == 0) {
		CloseHandle(file);
		return std::unique_ptr<MemoryMappedFile>(
		    new MemoryMappedFile(nullptr, 0));
	}

	HANDLE mapping =
	    CreateFileMappingA(file, NULL, PAGE_READONLY, 0, 0, NULL);
	// The view keeps the file/mapping alive, so the handles can be closed.
	CloseHandle(file);
	if (mapping == NULL)
		return nullptr;

	void* file_map = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
	CloseHandle(mapping);
	if (file_map == NULL)
		return nullptr;

	return std::unique_ptr<MemoryMappedFile>(new MemoryMappedFile(
	    file_map, static_cast<size_t>(file_size.QuadPart)));
#else
	int fd = open(path.c_str(), O_RDONLY, 0);
	if (fd == -1)
		return nullptr;

	struct stat statbuf;
	if (fstat(fd, &statbuf) < 0) {
		close(fd);
		return nullptr;
	}

	// mmap() will fail with EINVAL if length==0. If this file is
	// zero-length, return an object (to indicate the file exists) but
	// load it with a nullptr and zero length.
	if (statbuf.st_size == 0) {
		close(fd);
		return std::unique_ptr<MemoryMappedFile>(
		    new MemoryMappedFile(nullptr, 0));
	}

	void* file_map =
	    mmap(NULL, statbuf.st_size, PROT_READ, MAP_PRIVATE, fd, 0);

	// If mmap() succeeded, the fd is no longer needed as the mapping will
	// keep the file open.  If mmap() failed, the fd needs to be closed
	// anyway.
	close(fd);

	if (file_map == MAP_FAILED)
		return nullptr;

	return std::unique_ptr<MemoryMappedFile>(
	    new MemoryMappedFile(file_map, statbuf.st_size));
#endif
}

MemoryMappedFile::~MemoryMappedFile() {
#ifdef _WIN32
	if (data_)
		UnmapViewOfFile(data_);
#else
	munmap(data_, size_);
#endif
}

}  // namespace prjxray
