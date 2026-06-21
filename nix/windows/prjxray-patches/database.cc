/*
 * Copyright (C) 2017-2020  The Project X-Ray Authors.
 *
 * Use of this source code is governed by a ISC-style
 * license that can be found in the LICENSE file or at
 * https://opensource.org/licenses/ISC
 *
 * SPDX-License-Identifier: ISC
 */
#include <prjxray/database.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <glob.h>
#endif

#include <memory>

#include <absl/strings/str_cat.h>

namespace prjxray {

static constexpr const char kSegbitsGlobPattern[] = "segbits_*.db";

std::vector<std::unique_ptr<prjxray::SegbitsFileReader>> Database::segbits()
    const {
	std::vector<std::unique_ptr<prjxray::SegbitsFileReader>> segbits;

#ifdef _WIN32
	const std::string pattern =
	    absl::StrCat(db_path_, "/", kSegbitsGlobPattern);
	WIN32_FIND_DATAA find_data;
	HANDLE handle = FindFirstFileA(pattern.c_str(), &find_data);
	if (handle == INVALID_HANDLE_VALUE) {
		return {};
	}

	do {
		auto this_segbit = SegbitsFileReader::InitWithFile(
		    absl::StrCat(db_path_, "/", find_data.cFileName));
		if (this_segbit) {
			segbits.emplace_back(std::move(this_segbit));
		}
	} while (FindNextFileA(handle, &find_data));

	FindClose(handle);
#else
	glob_t segbits_glob_results;
	int ret = glob(absl::StrCat(db_path_, "/", kSegbitsGlobPattern).c_str(),
	               GLOB_NOSORT | GLOB_TILDE, NULL, &segbits_glob_results);
	if (ret < 0) {
		return {};
	}

	for (size_t idx = 0; idx < segbits_glob_results.gl_pathc; idx++) {
		auto this_segbit = SegbitsFileReader::InitWithFile(
		    segbits_glob_results.gl_pathv[idx]);
		if (this_segbit) {
			segbits.emplace_back(std::move(this_segbit));
		}
	}

	globfree(&segbits_glob_results);
#endif

	return segbits;
}

}  // namespace prjxray
