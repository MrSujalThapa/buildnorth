import { expect, test, vi } from "vitest";
import { saveProfileWithPhoto, type ProfileFields } from "./profileSave";

const previous: ProfileFields = { display_name: "Before", username: "user", bio: "Old" };
const next: ProfileFields = { display_name: "After", username: "user", bio: "New" };

test("a successful photo save keeps the new profile details", async () => {
  const saveDetails = vi.fn((fields: ProfileFields) => { expect(fields).toBeDefined(); return Promise.resolve(); });
  const savePhoto = vi.fn(() => Promise.resolve());
  await saveProfileWithPhoto(next, previous, saveDetails, savePhoto);
  expect(saveDetails).toHaveBeenCalledExactlyOnceWith(next);
  expect(savePhoto).toHaveBeenCalledOnce();
});

test("failed photo operation restores details before reporting failure", async () => {
  const saveDetails = vi.fn((fields: ProfileFields) => { expect(fields).toBeDefined(); return Promise.resolve(); });
  const savePhoto = vi.fn(() => Promise.reject(new Error("Upload unavailable")));
  await expect(saveProfileWithPhoto(next, previous, saveDetails, savePhoto)).rejects.toThrow("Upload unavailable");
  expect(saveDetails.mock.calls.map(([fields]) => fields)).toEqual([next, previous]);
});

test("failed restoration reports possible partial save", async () => {
  const saveDetails = vi.fn((fields: ProfileFields) => fields === previous
    ? Promise.reject(new Error("Database unavailable")) : Promise.resolve());
  const savePhoto = vi.fn(() => Promise.reject(new Error("Upload unavailable")));
  await expect(saveProfileWithPhoto(next, previous, saveDetails, savePhoto)).rejects.toThrow(
    "profile details may have changed",
  );
});
