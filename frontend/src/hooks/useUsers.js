import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as usersApi from "../api/users";

export const useUsers = () =>
  useQuery({
    queryKey: ["users"],
    queryFn: ({ signal }) => usersApi.listUsers(signal),
  });

export const useCreateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: usersApi.createUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });
};

export const useUpdateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, payload }) => usersApi.updateUser(userId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });
};

export const useDeactivateUser = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: usersApi.deactivateUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });
};

export const useResetUserPin = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, newPin }) => usersApi.resetUserPin(userId, newPin),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });
};
