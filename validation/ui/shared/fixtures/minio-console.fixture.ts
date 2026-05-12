import { test as base } from "./dataspace.fixture";

import { MinioConsoleRuntime, resolveMinioConsoleRuntime } from "../utils/minio-console-runtime";

type MinioConsoleFixtures = {
  minioConsoleRuntime: MinioConsoleRuntime;
};

export const test = base.extend<MinioConsoleFixtures>({
  minioConsoleRuntime: async ({}, use) => {
    await use(resolveMinioConsoleRuntime());
  },
});

export { expect } from "./dataspace.fixture";
