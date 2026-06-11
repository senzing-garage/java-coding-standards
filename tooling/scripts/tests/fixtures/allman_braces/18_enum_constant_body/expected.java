public enum Foo
{
    ALPHA
    {
        @Override
        public String describe()
        {
            return "alpha";
        }
    },
    BETA
    {
        @Override
        public String describe()
        {
            return "beta";
        }
    };

    public abstract String describe();
}
