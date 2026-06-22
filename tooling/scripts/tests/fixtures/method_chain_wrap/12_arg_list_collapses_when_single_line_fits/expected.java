public class Demo
{
    public boolean check(int modifiers, int returnTypeModifiers)
    {
        boolean isStatic = Modifier.isStatic(modifiers);
        if (!(Modifier.isPublic(modifiers)
              && Modifier.isStatic(modifiers)
              && Modifier.isPublic(returnTypeModifiers)))
        {
            return false;
        }
        return isStatic;
    }
}
